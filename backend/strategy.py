"""
Trading Strategy Engine — detects edge, sizes positions, and manages risk.
Implements fractional Kelly criterion for optimal bet sizing.
"""
import json
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """A trading signal with analysis and sizing."""
    market_ticker: str
    event_title: str
    sport: str                   # "tennis" or "baseball"
    side: str                    # "yes" or "no"
    model_probability: float     # Our estimated probability
    market_probability: float    # Market-implied probability
    edge: float                  # model_prob - market_prob
    confidence: float            # 0-1 confidence in our model
    kelly_fraction: float        # Optimal bet fraction
    suggested_size_dollars: float
    suggested_contracts: int
    price_cents: int             # Limit price
    analysis: Dict               # Full analysis breakdown
    timestamp: str = ""
    status: str = "pending"      # pending, placed, filled, expired, cancelled

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass  
class PortfolioState:
    """Tracks current portfolio state for risk management."""
    balance_cents: int = 0
    portfolio_value_cents: int = 0
    open_positions: List[Dict] = field(default_factory=list)
    daily_pnl_cents: int = 0
    daily_trades: int = 0
    last_loss_time: Optional[str] = None
    signals_generated: int = 0
    signals_traded: int = 0
    wins: int = 0
    losses: int = 0


class StrategyEngine:
    """
    Core strategy logic:
    1. Scans markets for tennis/baseball events
    2. Runs deep analysis on each match
    3. Compares model probability to market price
    4. Calculates edge and position size via Kelly
    5. Applies risk filters before signaling trade
    """

    def __init__(self, config):
        self.config = config
        self.portfolio = PortfolioState()
        self._trade_history: List[TradeSignal] = []
        self._daily_losses = 0.0
        self._last_reset_date = datetime.now().date()

    def _reset_daily_if_needed(self):
        today = datetime.now().date()
        if today != self._last_reset_date:
            self._daily_losses = 0.0
            self.portfolio.daily_pnl_cents = 0
            self.portfolio.daily_trades = 0
            self._last_reset_date = today

    # ── Edge Detection ────────────────────────────────────────────────

    def calculate_edge(
        self,
        model_probability: float,
        market_price_cents: int,
        side: str = "yes"
    ) -> Tuple[float, str]:
        """
        Calculate edge between our model and market price.
        Returns (edge_magnitude, recommended_side).
        
        Market price in cents = implied probability in %.
        E.g., YES at 60¢ = 60% implied probability.
        """
        market_prob = market_price_cents / 100.0
        
        if side == "yes":
            # We think YES is more likely than market says
            edge = model_probability - market_prob
            if edge > 0:
                return edge, "yes"
            else:
                # Check if NO side has edge
                no_edge = (1 - model_probability) - (1 - market_prob)
                if no_edge > 0:
                    return no_edge, "no"
                return edge, "yes"  # Negative edge
        else:
            edge = (1 - model_probability) - (1 - market_prob)
            return edge, "no"

    def kelly_criterion(
        self,
        probability: float,
        odds_decimal: float,
        fraction: float = 0.25
    ) -> float:
        """
        Fractional Kelly Criterion for optimal bet sizing.
        
        f* = (p * b - q) / b
        where:
          p = probability of winning
          q = 1 - p
          b = decimal odds - 1 (net odds)
          
        We use fractional Kelly (default 25%) to reduce variance.
        """
        if probability <= 0 or probability >= 1:
            return 0.0
        
        q = 1.0 - probability
        b = odds_decimal - 1.0
        
        if b <= 0:
            return 0.0
        
        kelly = (probability * b - q) / b
        kelly = max(0.0, kelly)
        
        # Apply fraction and cap
        sized = kelly * fraction
        sized = min(sized, self.config.trading.max_kelly_bet)
        
        return sized

    def size_position(
        self,
        model_prob: float,
        market_price_cents: int,
        side: str,
        bankroll_cents: int
    ) -> Tuple[int, float]:
        """
        Calculate position size in contracts and dollars.
        
        Returns: (num_contracts, dollar_amount)
        """
        if side == "yes":
            price = market_price_cents
            payout = 100  # $1.00 payout per contract
            odds_decimal = payout / price if price > 0 else 0
            win_prob = model_prob
        else:
            price = 100 - market_price_cents
            payout = 100
            odds_decimal = payout / price if price > 0 else 0
            win_prob = 1 - model_prob

        kelly_frac = self.kelly_criterion(
            win_prob, odds_decimal, self.config.trading.kelly_fraction
        )
        
        if kelly_frac <= 0:
            return 0, 0.0

        bankroll_dollars = bankroll_cents / 100.0
        bet_dollars = bankroll_dollars * kelly_frac
        
        # Apply hard caps
        bet_dollars = min(bet_dollars, self.config.trading.max_position_size_dollars)
        
        # Calculate contracts
        price_dollars = price / 100.0
        contracts = int(bet_dollars / price_dollars) if price_dollars > 0 else 0
        contracts = max(1, min(contracts, 100))  # At least 1, max 100
        
        actual_cost = contracts * price_dollars
        
        return contracts, actual_cost

    # ── Risk Filters ──────────────────────────────────────────────────

    def passes_risk_checks(self, signal: TradeSignal) -> Tuple[bool, str]:
        """Apply all risk management filters. Returns (pass, reason)."""
        self._reset_daily_if_needed()
        tc = self.config.trading
        
        # 1. Minimum edge threshold
        if abs(signal.edge) < tc.min_edge_threshold:
            return False, f"Edge {signal.edge:.3f} below threshold {tc.min_edge_threshold}"
        
        # 2. Minimum confidence
        if signal.confidence < tc.min_confidence:
            return False, f"Confidence {signal.confidence:.3f} below threshold {tc.min_confidence}"
        
        # 3. Daily loss limit
        if self._daily_losses >= tc.max_daily_loss_dollars:
            return False, f"Daily loss limit reached: ${self._daily_losses:.2f}"
        
        # 4. Max open positions
        if len(self.portfolio.open_positions) >= tc.max_open_positions:
            return False, f"Max open positions ({tc.max_open_positions}) reached"
        
        # 5. Post-loss cooldown
        if self.portfolio.last_loss_time:
            last_loss = datetime.fromisoformat(self.portfolio.last_loss_time)
            cooldown_end = last_loss + timedelta(minutes=tc.cooldown_after_loss_minutes)
            if datetime.now() < cooldown_end:
                return False, f"Cooldown active until {cooldown_end.isoformat()}"
        
        # 6. Position size sanity
        if signal.suggested_size_dollars > tc.max_position_size_dollars:
            return False, f"Size ${signal.suggested_size_dollars:.2f} exceeds max ${tc.max_position_size_dollars}"
        
        # 7. Don't bet on extreme markets (near 0 or 100)
        if signal.market_probability < 0.05 or signal.market_probability > 0.95:
            return False, f"Market too extreme: {signal.market_probability:.0%}"
        
        return True, "All checks passed"

    # ── Signal Generation ─────────────────────────────────────────────

    def generate_tennis_signal(
        self,
        market: Dict,
        analysis: Dict
    ) -> Optional[TradeSignal]:
        """Generate a trade signal from tennis match analysis."""
        ticker = market.get("ticker", "")
        title = market.get("_event_title", market.get("title", ""))
        
        # Get market price
        yes_bid = market.get("yes_bid_dollars")
        yes_ask = market.get("yes_ask_dollars")
        last_price = market.get("last_price_dollars")
        
        # Use midpoint or last price
        if yes_bid and yes_ask:
            try:
                mid = (float(yes_bid) + float(yes_ask)) / 2
                market_price_cents = int(mid * 100)
            except (ValueError, TypeError):
                market_price_cents = 50
        elif last_price:
            try:
                market_price_cents = int(float(last_price) * 100)
            except (ValueError, TypeError):
                market_price_cents = 50
        else:
            market_price_cents = 50

        model_prob = analysis["p1_win_probability"]
        market_prob = market_price_cents / 100.0
        
        edge, side = self.calculate_edge(model_prob, market_price_cents)
        
        if abs(edge) < self.config.trading.min_edge_threshold:
            return None

        contracts, cost = self.size_position(
            model_prob, market_price_cents, side,
            self.portfolio.balance_cents or 100_00  # Default $100
        )

        if contracts == 0:
            return None

        price = market_price_cents if side == "yes" else (100 - market_price_cents)

        signal = TradeSignal(
            market_ticker=ticker,
            event_title=title,
            sport="tennis",
            side=side,
            model_probability=model_prob,
            market_probability=market_prob,
            edge=round(edge, 4),
            confidence=analysis["confidence"],
            kelly_fraction=self.kelly_criterion(
                model_prob if side == "yes" else (1 - model_prob),
                100 / price if price > 0 else 0,
                self.config.trading.kelly_fraction
            ),
            suggested_size_dollars=round(cost, 2),
            suggested_contracts=contracts,
            price_cents=price,
            analysis=analysis,
        )

        self.portfolio.signals_generated += 1
        return signal

    def generate_baseball_signal(
        self,
        market: Dict,
        analysis: Dict
    ) -> Optional[TradeSignal]:
        """Generate a trade signal from baseball game analysis."""
        ticker = market.get("ticker", "")
        title = market.get("_event_title", market.get("title", ""))
        
        yes_bid = market.get("yes_bid_dollars")
        yes_ask = market.get("yes_ask_dollars")
        last_price = market.get("last_price_dollars")
        
        if yes_bid and yes_ask:
            try:
                mid = (float(yes_bid) + float(yes_ask)) / 2
                market_price_cents = int(mid * 100)
            except (ValueError, TypeError):
                market_price_cents = 50
        elif last_price:
            try:
                market_price_cents = int(float(last_price) * 100)
            except (ValueError, TypeError):
                market_price_cents = 50
        else:
            market_price_cents = 50

        # Home team = YES side (conventional)
        model_prob = analysis["home_win_probability"]
        market_prob = market_price_cents / 100.0
        
        edge, side = self.calculate_edge(model_prob, market_price_cents)
        
        if abs(edge) < self.config.trading.min_edge_threshold:
            return None

        contracts, cost = self.size_position(
            model_prob, market_price_cents, side,
            self.portfolio.balance_cents or 100_00
        )

        if contracts == 0:
            return None

        price = market_price_cents if side == "yes" else (100 - market_price_cents)

        signal = TradeSignal(
            market_ticker=ticker,
            event_title=title,
            sport="baseball",
            side=side,
            model_probability=model_prob,
            market_probability=market_prob,
            edge=round(edge, 4),
            confidence=analysis["confidence"],
            kelly_fraction=self.kelly_criterion(
                model_prob if side == "yes" else (1 - model_prob),
                100 / price if price > 0 else 0,
                self.config.trading.kelly_fraction
            ),
            suggested_size_dollars=round(cost, 2),
            suggested_contracts=contracts,
            price_cents=price,
            analysis=analysis,
        )

        self.portfolio.signals_generated += 1
        return signal

    def record_trade_result(self, signal: TradeSignal, won: bool, pnl_dollars: float):
        """Record a completed trade for tracking."""
        if won:
            self.portfolio.wins += 1
        else:
            self.portfolio.losses += 1
            self._daily_losses += abs(pnl_dollars)
            self.portfolio.last_loss_time = datetime.now().isoformat()
        
        self.portfolio.daily_pnl_cents += int(pnl_dollars * 100)
        self._trade_history.append(signal)

    def get_stats(self) -> Dict:
        """Get strategy performance statistics."""
        total = self.portfolio.wins + self.portfolio.losses
        return {
            "signals_generated": self.portfolio.signals_generated,
            "signals_traded": self.portfolio.signals_traded,
            "wins": self.portfolio.wins,
            "losses": self.portfolio.losses,
            "win_rate": self.portfolio.wins / max(total, 1),
            "daily_pnl_cents": self.portfolio.daily_pnl_cents,
            "daily_losses": self._daily_losses,
            "open_positions": len(self.portfolio.open_positions),
            "balance_cents": self.portfolio.balance_cents,
        }
