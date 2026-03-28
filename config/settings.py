"""
Configuration settings for Kalshi Sports Trading Bot.
Edit .env file or set environment variables before running.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class KalshiConfig:
    """Kalshi API configuration."""
    api_key_id: str = ""
    private_key_path: str = ""
    base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    demo_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    use_demo: bool = True  # Start in demo mode for safety

    @property
    def active_url(self) -> str:
        return self.demo_url if self.use_demo else self.base_url

@dataclass
class TradingConfig:
    """Risk management & trading parameters."""
    max_position_size_dollars: float = 50.0      # Max $ per single position
    max_daily_loss_dollars: float = 200.0         # Stop trading if daily loss exceeds
    max_open_positions: int = 10                   # Max concurrent open positions
    min_edge_threshold: float = 0.08               # Min edge (model_prob - market_prob) to trade
    min_confidence: float = 0.60                   # Min model confidence to consider
    kelly_fraction: float = 0.25                   # Fraction of Kelly criterion for sizing
    max_kelly_bet: float = 0.10                    # Max fraction of bankroll per bet
    cooldown_after_loss_minutes: int = 30           # Wait after a losing trade
    stale_market_threshold_minutes: int = 5         # Skip markets with no recent activity

@dataclass 
class TennisConfig:
    """Tennis-specific analysis weights."""
    weight_surface: float = 0.20          # Court surface advantage
    weight_form: float = 0.25            # Recent form (last 10 matches)
    weight_h2h: float = 0.15             # Head-to-head record
    weight_fatigue: float = 0.15         # Schedule density / recovery
    weight_ranking: float = 0.10         # Current ranking gap
    weight_serve: float = 0.10           # Serve statistics
    weight_mental: float = 0.05          # Tiebreak/deciding set record

@dataclass
class BaseballConfig:
    """Baseball-specific analysis weights."""
    weight_pitching: float = 0.25        # Starting pitcher quality
    weight_batting: float = 0.20         # Team batting vs pitcher type
    weight_bullpen: float = 0.15         # Bullpen strength/rest
    weight_park_factor: float = 0.10     # Ballpark run environment
    weight_weather: float = 0.05         # Wind, temp, humidity
    weight_recent_form: float = 0.15     # Last 10 games record
    weight_injuries: float = 0.10        # Key player availability

@dataclass
class BotConfig:
    """Master configuration."""
    kalshi: KalshiConfig = field(default_factory=KalshiConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    tennis: TennisConfig = field(default_factory=TennisConfig)
    baseball: BaseballConfig = field(default_factory=BaseballConfig)
    scan_interval_seconds: int = 120     # How often to scan for new markets
    log_level: str = "INFO"

def load_config() -> BotConfig:
    """Load config from environment variables."""
    config = BotConfig()
    config.kalshi.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
    config.kalshi.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    config.kalshi.use_demo = os.getenv("KALSHI_USE_DEMO", "true").lower() == "true"
    config.trading.max_position_size_dollars = float(os.getenv("MAX_POSITION_DOLLARS", "50"))
    config.trading.max_daily_loss_dollars = float(os.getenv("MAX_DAILY_LOSS_DOLLARS", "200"))
    config.trading.min_edge_threshold = float(os.getenv("MIN_EDGE_THRESHOLD", "0.08"))
    config.trading.kelly_fraction = float(os.getenv("KELLY_FRACTION", "0.25"))
    config.scan_interval_seconds = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))
    return config
