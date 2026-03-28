# Kalshi Sports Trading Bot — Tennis & Baseball

Automated prediction market trading bot for Kalshi, specializing in tennis and baseball markets. Performs deep analysis on every match, detects edge vs market prices, and executes trades with strict risk management.

## Architecture

```
┌─────────────────────────────────────────────┐
│             Dashboard (Web UI)               │
│  Status │ Signals │ Analysis │ Config │ Logs │
└─────────────────┬───────────────────────────┘
                  │ REST API
┌─────────────────┴───────────────────────────┐
│            FastAPI Server (server.py)         │
└──┬──────────┬──────────┬──────────┬─────────┘
   │          │          │          │
┌──┴──┐  ┌───┴───┐  ┌───┴───┐  ┌──┴──────┐
│ Bot │  │Kalshi │  │Sports │  │Strategy │
│ Loop│  │Client │  │ Data  │  │ Engine  │
└─────┘  └───────┘  └───────┘  └─────────┘
```

## Features

### Tennis Analysis Engine
- **Surface performance**: Hard/clay/grass win rate differentials
- **Fatigue tracking**: Days since last match, matches in last 30 days, travel burden
- **Head-to-head**: Historical matchup record + surface-specific H2H
- **Recent form**: Last 10 match results with weighted recency
- **Ranking differential**: Normalized ATP/WTA ranking gap
- **Serve dominance**: Ace rate, first serve %, service games won
- **Mental strength**: Tiebreak record, deciding set performance

### Baseball Analysis Engine
- **Starting pitcher**: ERA, WHIP, K/9, BB/9, HR/9 via MLB Stats API
- **Team batting**: AVG, OBP, SLG, OPS, runs per game
- **Bullpen strength**: Relief ERA, WHIP, saves/blown saves
- **Park factors**: Built-in park factor database (Coors: 1.35, Oracle: 0.93, etc.)
- **Weather impact**: Temperature, wind direction, humidity adjustments
- **Recent form**: Last 10 game record, run differential, streaks
- **Injury impact**: Key player availability (placeholder for news API)

### Trading System
- **Edge detection**: Compares model probability to market-implied probability
- **Kelly criterion**: Fractional Kelly (25% default) for optimal bet sizing
- **Risk management**:
  - Max position size per trade ($50 default)
  - Max daily loss limit ($200 default)
  - Max concurrent open positions (10)
  - Post-loss cooldown period (30 minutes)
  - Extreme market filter (avoids >95% / <5% markets)
  - Minimum edge threshold (8% default)
  - Minimum confidence threshold (60%)

### Dashboard
- Real-time status (running/stopped, paper/live mode)
- KPI cards: Balance, signals, trades, win rate, daily P&L
- Trade signals table with sport filter
- Match analysis breakdowns with factor visualization
- Live MLB schedule with game-by-game analysis
- Configuration panel for runtime parameter tuning
- Log viewer
- API credential management

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure credentials
Copy the example env file and fill in your Kalshi API credentials:
```bash
cp .env.example .env
```

Or configure via the dashboard UI (API Keys button).

### 3. Generate Kalshi API keys
1. Log into [Kalshi](https://kalshi.com/account/profile)
2. Navigate to Profile Settings → API Keys
3. Click "Create New API Key"
4. Save the Key ID and private key PEM file

### 4. Start the bot
```bash
python server.py
```
Then open `http://localhost:5000` in your browser.

### 5. Recommended startup flow
1. Start in **demo mode** (default) with paper trading
2. Click "Scan Now" to see analyses without placing trades
3. Review signals and tune parameters via Config
4. When ready, enter live API credentials and switch to "Live" mode

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Full bot state |
| POST | `/api/scan` | Trigger manual scan |
| POST | `/api/start` | Start auto-scanning loop |
| POST | `/api/stop` | Stop scanning |
| POST | `/api/mode` | Switch paper/live |
| POST | `/api/config` | Update parameters |
| POST | `/api/credentials` | Set Kalshi API keys |
| GET | `/api/signals` | Trade signal history |
| GET | `/api/markets/tennis` | Current tennis markets |
| GET | `/api/markets/baseball` | Current baseball markets |
| GET | `/api/mlb/schedule` | Today's MLB games + analysis |
| GET | `/api/logs` | Bot log output |
| GET | `/api/scan-history` | Scan history |

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_EDGE_THRESHOLD` | 0.08 | Minimum edge (8%) to consider trading |
| `MIN_CONFIDENCE` | 0.60 | Minimum model confidence |
| `MAX_POSITION_DOLLARS` | 50 | Max $ per single trade |
| `MAX_DAILY_LOSS_DOLLARS` | 200 | Daily loss limit |
| `KELLY_FRACTION` | 0.25 | Kelly criterion multiplier |
| `SCAN_INTERVAL_SECONDS` | 120 | Seconds between auto-scans |

## File Structure

```
kalshi-sports-bot/
├── server.py                  # FastAPI server & dashboard host
├── requirements.txt
├── .env.example
├── config/
│   ├── __init__.py
│   └── settings.py            # All configuration & weights
├── backend/
│   ├── __init__.py
│   ├── kalshi_client.py       # Kalshi API (auth, markets, orders)
│   ├── sports_data.py         # Tennis & baseball data providers
│   ├── strategy.py            # Edge detection, Kelly sizing, risk mgmt
│   └── bot.py                 # Main bot loop & orchestration
├── frontend/
│   └── dist/
│       └── index.html         # Dashboard SPA
└── data/
    ├── bot.log                # Runtime logs
    └── scan_history.jsonl     # Scan results
```

## Risk Disclaimer

This bot trades real money on Kalshi when in live mode. Use at your own risk. Start with the demo environment and paper trading. The model's probability estimates are not guaranteed to be accurate. Past performance does not predict future results.
