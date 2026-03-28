"""
Main Trading Bot — orchestrates market scanning, analysis, and trade execution.
Runs as an async loop with configurable scan intervals.
"""
import asyncio
import json
import logging
import os
import re
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from config.settings import BotConfig, load_config
from backend.kalshi_client import KalshiClient, KalshiPublicClient
from backend.sports_data import TennisDataProvider, BaseballDataProvider
from backend.strategy import StrategyEngine, TradeSignal

logger = logging.getLogger(__name__)

# Log storage
LOG_DIR = Path(__file__).parent.parent / "data"
LOG_DIR.mkdir(exist_ok=True)


class TradingBot:
    """
    The main bot loop:
    1. Scan Kalshi for open tennis/baseball markets
    2. Parse matchup from market title
    3. Fetch deep sports analysis
    4. Compare model probability to market price
    5. Size and execute trades when edge is found
    """

    def __init__(self, config: Optional[BotConfig] = None):
        self.config = config or load_config()
        self._running = False
        self._mode = "paper"  # "paper" or "live"
        
        # Initialize components
        if self.config.kalshi.api_key_id and self.config.kalshi.private_key_path:
            self.kalshi = KalshiClient(
                api_key_id=self.config.kalshi.api_key_id,
                private_key_path=self.config.kalshi.private_key_path,
                base_url=self.config.kalshi.active_url,
            )
        else:
            self.kalshi = None

        self.kalshi_public = KalshiPublicClient()
        self.tennis = TennisDataProvider()
        self.baseball = BaseballDataProvider()
        self.strategy = StrategyEngine(self.config)
        
        # State
        self._signals: List[TradeSignal] = []
        self._active_signals: List[TradeSignal] = []
        self._scan_count = 0
        self._last_scan_time = None
        self._errors: List[Dict] = []

    @property
    def is_authenticated(self) -> bool:
        return self.kalshi is not None

    # ── Market Parsing ────────────────────────────────────────────────

    def _parse_tennis_match(self, market: Dict) -> Optional[Dict]:
        """
        Parse player names, tournament, surface from market title.
        Kalshi tennis market titles are typically like:
        "Player1 vs Player2" or "Will Player1 beat Player2?"
        """
        title = market.get("title", "") or market.get("_event_title", "")
        if not title:
            return None

        # Common patterns
        vs_match = re.search(r'(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)(?:\s*[-–—]|\s*\?|$)', title, re.IGNORECASE)
        beat_match = re.search(r'Will\s+(.+?)\s+beat\s+(.+?)\?', title, re.IGNORECASE)
        win_match = re.search(r'(.+?)\s+(?:to win|wins?)\s+(?:vs\.?|against)\s+(.+?)(?:\s*[-–—]|\s*\?|$)', title, re.IGNORECASE)

        match = vs_match or beat_match or win_match
        if not match:
            return None

        player1 = match.group(1).strip()
        player2 = match.group(2).strip()

        # Try to detect surface from event/title
        surface = "hard"  # default
        combined = title.lower()
        if any(kw in combined for kw in ["roland garros", "french open", "clay", "terre battue", "rome", "madrid", "monte carlo"]):
            surface = "clay"
        elif any(kw in combined for kw in ["wimbledon", "grass", "queen", "halle", "stuttgart"]):
            surface = "grass"

        # Detect tournament
        tournament = ""
        for t in ["Australian Open", "French Open", "Roland Garros", "Wimbledon", 
                   "US Open", "Indian Wells", "Miami Open", "Madrid", "Rome",
                   "Monte Carlo", "Cincinnati", "Canadian Open", "Shanghai"]:
            if t.lower() in combined:
                tournament = t
                break

        return {
            "player1": player1,
            "player2": player2,
            "surface": surface,
            "tournament": tournament,
        }

    def _parse_baseball_game(self, market: Dict) -> Optional[Dict]:
        """
        Parse teams from market title.
        Titles like "Yankees vs Red Sox" or "Will the Dodgers beat the Mets?"
        """
        title = market.get("title", "") or market.get("_event_title", "")
        if not title:
            return None

        MLB_TEAMS = [
            "Yankees", "Red Sox", "Blue Jays", "Rays", "Orioles",
            "White Sox", "Guardians", "Tigers", "Royals", "Twins",
            "Astros", "Mariners", "Angels", "Athletics", "Rangers",
            "Mets", "Braves", "Phillies", "Marlins", "Nationals",
            "Cubs", "Cardinals", "Brewers", "Reds", "Pirates",
            "Dodgers", "Padres", "Giants", "Diamondbacks", "Rockies",
            "New York Yankees", "Boston Red Sox", "Toronto Blue Jays",
            "Tampa Bay Rays", "Baltimore Orioles", "Chicago White Sox",
            "Cleveland Guardians", "Detroit Tigers", "Kansas City Royals",
            "Minnesota Twins", "Houston Astros", "Seattle Mariners",
            "Los Angeles Angels", "Oakland Athletics", "Texas Rangers",
            "New York Mets", "Atlanta Braves", "Philadelphia Phillies",
            "Miami Marlins", "Washington Nationals", "Chicago Cubs",
            "St. Louis Cardinals", "Milwaukee Brewers", "Cincinnati Reds",
            "Pittsburgh Pirates", "Los Angeles Dodgers", "San Diego Padres",
            "San Francisco Giants", "Arizona Diamondbacks", "Colorado Rockies",
        ]

        title_lower = title.lower()
        found_teams = []
        for team in MLB_TEAMS:
            if team.lower() in title_lower:
                found_teams.append(team)

        if len(found_teams) < 2:
            # Try vs pattern
            vs_match = re.search(r'(.+?)\s+(?:vs\.?|v\.?|at)\s+(.+?)(?:\s*[-–—]|\s*\?|$)', title, re.IGNORECASE)
            if vs_match:
                return {
                    "away_team": vs_match.group(1).strip(),
                    "home_team": vs_match.group(2).strip(),
                }
            return None

        # First team mentioned is usually away, second is home
        return {
            "away_team": found_teams[0],
            "home_team": found_teams[1] if len(found_teams) > 1 else found_teams[0],
        }

    # ── Scan & Analyze ────────────────────────────────────────────────

    def scan_tennis(self) -> List[TradeSignal]:
        """Scan all open tennis markets and generate signals."""
        signals = []
        try:
            if self.is_authenticated:
                markets = self.kalshi.find_tennis_markets()
            else:
                # Use public API with keyword search
                data = self.kalshi_public.get_events(status="open", limit=200)
                markets = []
                for event in data.get("events", []):
                    title = (event.get("title", "") + " " + event.get("category", "")).lower()
                    if any(kw in title for kw in ["tennis", "atp", "wta", "grand slam", "wimbledon"]):
                        for m in event.get("markets", []):
                            m["_event_title"] = event.get("title", "")
                            markets.append(m)

            logger.info(f"Found {len(markets)} tennis markets")

            for market in markets:
                if market.get("status") != "open":
                    continue
                    
                parsed = self._parse_tennis_match(market)
                if not parsed:
                    continue

                analysis = self.tennis.analyze_match(
                    player1=parsed["player1"],
                    player2=parsed["player2"],
                    surface=parsed["surface"],
                    tournament=parsed.get("tournament", ""),
                )

                signal = self.strategy.generate_tennis_signal(market, analysis)
                if signal:
                    passes, reason = self.strategy.passes_risk_checks(signal)
                    if passes:
                        signals.append(signal)
                        logger.info(
                            f"Tennis signal: {signal.event_title} | "
                            f"{signal.side} @ {signal.price_cents}¢ | "
                            f"Edge: {signal.edge:.1%} | Conf: {signal.confidence:.1%}"
                        )
                    else:
                        logger.debug(f"Tennis signal rejected: {reason}")

        except Exception as e:
            logger.error(f"Tennis scan error: {e}")
            self._errors.append({"time": datetime.now().isoformat(), "error": str(e), "sport": "tennis"})

        return signals

    def scan_baseball(self) -> List[TradeSignal]:
        """Scan all open baseball markets and generate signals."""
        signals = []
        try:
            if self.is_authenticated:
                markets = self.kalshi.find_baseball_markets()
            else:
                data = self.kalshi_public.get_events(status="open", limit=200)
                markets = []
                for event in data.get("events", []):
                    title = (event.get("title", "") + " " + event.get("category", "")).lower()
                    if any(kw in title for kw in ["baseball", "mlb", "world series", "yankees", "dodgers", "mets"]):
                        for m in event.get("markets", []):
                            m["_event_title"] = event.get("title", "")
                            markets.append(m)

            logger.info(f"Found {len(markets)} baseball markets")

            # Also get today's MLB schedule for enrichment
            schedule = self.baseball.get_schedule()

            for market in markets:
                if market.get("status") != "open":
                    continue

                parsed = self._parse_baseball_game(market)
                if not parsed:
                    continue

                # Try to match with MLB schedule for enriched data
                matched_game = None
                for game in schedule:
                    away_name = game["away_team"]["name"].lower()
                    home_name = game["home_team"]["name"].lower()
                    parsed_away = parsed["away_team"].lower()
                    parsed_home = parsed["home_team"].lower()
                    if (parsed_away in away_name or away_name in parsed_away) and \
                       (parsed_home in home_name or home_name in parsed_home):
                        matched_game = game
                        break

                if matched_game:
                    analysis = self.baseball.analyze_game(matched_game)
                else:
                    # Create a minimal analysis without MLB API data
                    analysis = {
                        "away_team": parsed["away_team"],
                        "home_team": parsed["home_team"],
                        "home_win_probability": 0.54,  # Home advantage baseline
                        "away_win_probability": 0.46,
                        "confidence": 0.1,
                        "factors": {},
                        "raw_edge": 0.04,
                    }

                signal = self.strategy.generate_baseball_signal(market, analysis)
                if signal:
                    passes, reason = self.strategy.passes_risk_checks(signal)
                    if passes:
                        signals.append(signal)
                        logger.info(
                            f"Baseball signal: {signal.event_title} | "
                            f"{signal.side} @ {signal.price_cents}¢ | "
                            f"Edge: {signal.edge:.1%} | Conf: {signal.confidence:.1%}"
                        )
                    else:
                        logger.debug(f"Baseball signal rejected: {reason}")

        except Exception as e:
            logger.error(f"Baseball scan error: {e}")
            self._errors.append({"time": datetime.now().isoformat(), "error": str(e), "sport": "baseball"})

        return signals

    # ── Trade Execution ───────────────────────────────────────────────

    def execute_signal(self, signal: TradeSignal) -> bool:
        """Execute a trade signal on Kalshi."""
        if self._mode == "paper":
            logger.info(f"[PAPER] Would trade: {signal.side} {signal.suggested_contracts}x "
                       f"@ {signal.price_cents}¢ on {signal.market_ticker}")
            signal.status = "paper_filled"
            self._signals.append(signal)
            self.strategy.portfolio.signals_traded += 1
            return True

        if not self.is_authenticated:
            logger.warning("Cannot execute: no Kalshi credentials configured")
            return False

        try:
            result = self.kalshi.create_order(
                ticker=signal.market_ticker,
                side=signal.side,
                action="buy",
                count=signal.suggested_contracts,
                price_cents=signal.price_cents,
            )
            order = result.get("order", {})
            signal.status = order.get("status", "placed")
            self._signals.append(signal)
            self.strategy.portfolio.signals_traded += 1
            logger.info(f"Order placed: {order.get('order_id')} status={signal.status}")
            return True

        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            signal.status = "error"
            self._errors.append({
                "time": datetime.now().isoformat(),
                "error": str(e),
                "signal": signal.market_ticker,
            })
            return False

    # ── Main Loop ─────────────────────────────────────────────────────

    async def run_scan(self) -> Dict:
        """Run a single scan cycle."""
        self._scan_count += 1
        self._last_scan_time = datetime.now().isoformat()
        
        logger.info(f"=== Scan #{self._scan_count} at {self._last_scan_time} ===")

        # Update portfolio state if authenticated
        if self.is_authenticated:
            try:
                balance = self.kalshi.get_balance()
                self.strategy.portfolio.balance_cents = balance.get("balance", 0)
                self.strategy.portfolio.portfolio_value_cents = balance.get("portfolio_value", 0)
            except Exception as e:
                logger.warning(f"Balance fetch failed: {e}")

        # Scan both sports
        tennis_signals = self.scan_tennis()
        baseball_signals = self.scan_baseball()
        all_signals = tennis_signals + baseball_signals

        # Execute signals
        executed = 0
        for signal in all_signals:
            if self.execute_signal(signal):
                executed += 1

        result = {
            "scan_number": self._scan_count,
            "timestamp": self._last_scan_time,
            "tennis_signals": len(tennis_signals),
            "baseball_signals": len(baseball_signals),
            "executed": executed,
            "total_signals_history": len(self._signals),
            "strategy_stats": self.strategy.get_stats(),
        }

        # Save scan log
        self._save_scan_log(result)
        
        return result

    def _save_scan_log(self, result: Dict):
        """Persist scan results to disk."""
        log_file = LOG_DIR / "scan_history.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(result, default=str) + "\n")

    async def run(self):
        """Main bot loop."""
        self._running = True
        logger.info(f"Bot starting in {self._mode} mode, scan interval: {self.config.scan_interval_seconds}s")
        
        while self._running:
            try:
                await self.run_scan()
            except Exception as e:
                logger.error(f"Scan cycle error: {traceback.format_exc()}")
                self._errors.append({
                    "time": datetime.now().isoformat(),
                    "error": str(e),
                })
            
            await asyncio.sleep(self.config.scan_interval_seconds)

    def stop(self):
        """Stop the bot loop."""
        self._running = False
        logger.info("Bot stopped")

    # ── API for Dashboard ─────────────────────────────────────────────

    def get_state(self) -> Dict:
        """Get full bot state for the dashboard."""
        return {
            "running": self._running,
            "mode": self._mode,
            "scan_count": self._scan_count,
            "last_scan_time": self._last_scan_time,
            "authenticated": self.is_authenticated,
            "config": {
                "scan_interval": self.config.scan_interval_seconds,
                "min_edge": self.config.trading.min_edge_threshold,
                "min_confidence": self.config.trading.min_confidence,
                "max_position": self.config.trading.max_position_size_dollars,
                "max_daily_loss": self.config.trading.max_daily_loss_dollars,
                "kelly_fraction": self.config.trading.kelly_fraction,
                "use_demo": self.config.kalshi.use_demo,
            },
            "strategy_stats": self.strategy.get_stats(),
            "recent_signals": [s.to_dict() for s in self._signals[-20:]],
            "errors": self._errors[-10:],
        }

    def set_mode(self, mode: str):
        if mode in ("paper", "live"):
            self._mode = mode
            logger.info(f"Mode changed to: {mode}")

    def update_config(self, updates: Dict):
        """Update config parameters at runtime."""
        if "min_edge" in updates:
            self.config.trading.min_edge_threshold = float(updates["min_edge"])
        if "min_confidence" in updates:
            self.config.trading.min_confidence = float(updates["min_confidence"])
        if "max_position" in updates:
            self.config.trading.max_position_size_dollars = float(updates["max_position"])
        if "max_daily_loss" in updates:
            self.config.trading.max_daily_loss_dollars = float(updates["max_daily_loss"])
        if "kelly_fraction" in updates:
            self.config.trading.kelly_fraction = float(updates["kelly_fraction"])
        if "scan_interval" in updates:
            self.config.scan_interval_seconds = int(updates["scan_interval"])
        logger.info(f"Config updated: {updates}")
