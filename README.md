# Kalshi Sports Trading Bot — Tennis & Baseball

Automated prediction market trading bot for Kalshi, specializing in tennis and baseball markets. Performs deep analysis on every match, detects edge vs market prices, and executes trades with strict risk management.

**Two deployment options:**
- **GitHub Pages** — static dashboard that runs entirely in the browser (recommended)
- **Local Python** — FastAPI server with full backend (advanced)

---

## Quick Start — GitHub Pages

### 1. Fork or clone this repo

```bash
git clone https://github.com/YOUR_USERNAME/kalshi-sports-bot.git
```

### 2. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **GitHub Actions**
3. Push to the `main` branch — the workflow deploys automatically

Your dashboard will be live at:
```
https://YOUR_USERNAME.github.io/kalshi-sports-bot/
```

### 3. Connect your Kalshi API keys

1. Open the deployed dashboard
2. Click **API Keys** in the top-right
3. Paste your Key ID and private key PEM
4. Check **Use Demo Environment** to start in sandbox mode
5. Click **Connect**

> Credentials are only stored in your browser's memory for the current session. They never leave your machine — all API signing happens client-side using the Web Crypto API.

### 4. Start trading

1. Click **Scan Now** to run a one-time analysis of available markets
2. Review signals in the table and match analyses in the Analysis tab
3. Click **Start** to begin automated scanning at the configured interval
4. Adjust parameters in the Config panel (edge threshold, Kelly fraction, etc.)
5. When ready, switch from Paper to **Live** mode to execute real trades

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│               Static Dashboard (docs/)                       │
│   GitHub Pages — runs 100% in the browser                    │
│                                                              │
│   ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐ │
│   │  Kalshi   │  │  Sports   │  │ Strategy │  │    Bot    │ │
│   │  Client   │  │   Data    │  │  Engine  │  │ Orchestr. │ │
│   │(Web Crypto│  │ (MLB API) │  │ (Kelly,  │  │(setInterval│ │
│   │ RSA-PSS) │  │           │  │  Risk)   │  │   loop)   │ │
│   └──────────┘  └───────────┘  └──────────┘  └───────────┘ │
└──────────────────────────────────────────────────────────────┘
         │                │
         ▼                ▼
  Kalshi API        MLB Stats API
  (trade-api/v2)    (statsapi.mlb.com)
```

## Features

### Tennis Analysis Engine
- **Surface performance** — hard/clay/grass win rate differentials
- **Fatigue tracking** — days since last match, matches in last 30 days, travel burden
- **Head-to-head** — historical matchup record + surface-specific H2H
- **Recent form** — last 10 match results with weighted recency
- **Ranking differential** — normalized ATP/WTA ranking gap
- **Serve dominance** — ace rate, first serve %, service games won
- **Mental strength** — tiebreak record, deciding set performance

### Baseball Analysis Engine
- **Starting pitcher** — ERA, WHIP, K/9, BB/9, HR/9 via MLB Stats API
- **Team batting** — AVG, OBP, SLG, OPS, runs per game
- **Bullpen strength** — relief ERA, WHIP, saves/blown saves
- **Park factors** — built-in database for all 30 parks (Coors: 1.35, Oracle: 0.93, etc.)
- **Weather impact** — temperature, wind direction, humidity adjustments
- **Recent form** — last 10 game record, run differential, streaks
- **Injury impact** — key player availability (placeholder for news API)

### Trading System
- **Edge detection** — compares model probability to market-implied probability
- **Kelly criterion** — fractional Kelly (25% default) for optimal bet sizing
- **Risk management:**
  - Max position size per trade ($50 default)
  - Max daily loss limit ($200 default)
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
- API credential management (browser-only, never sent to a server)

---

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Min Edge Threshold | 0.08 | Minimum edge (8%) to consider trading |
| Min Confidence | 0.60 | Minimum model confidence |
| Max Position ($) | 50 | Max $ per single trade |
| Max Daily Loss ($) | 200 | Daily loss limit |
| Kelly Fraction | 0.25 | Kelly criterion multiplier |
| Scan Interval (sec) | 120 | Seconds between auto-scans |

All config changes are saved to `localStorage` and persist across browser sessions.

---

## Generating Kalshi API Keys

1. Log into [Kalshi](https://kalshi.com/account/profile)
2. Navigate to **Profile Settings → API Keys**
3. Click **Create New API Key**
4. Save the Key ID and download the private key PEM file
5. For testing, use the [Demo environment](https://demo.kalshi.co) and generate demo keys there

---

## Local Python Server (Advanced)

If you prefer running the backend locally instead of the static GitHub Pages version:

### Install dependencies
```bash
pip install -r requirements.txt
```

### Configure credentials
```bash
cp .env.example .env
# Edit .env with your Kalshi API credentials
```

### Start the server
```bash
python server.py
```

Open `http://localhost:5000` in your browser.

---

## File Structure

```
kalshi-sports-bot/
├── docs/                          # GitHub Pages static dashboard
│   ├── index.html                 # Full SPA dashboard
│   └── js/
│       ├── kalshi-client.js       # Browser Kalshi API (Web Crypto RSA-PSS)
│       ├── sports-data.js         # MLB Stats API + baseball/tennis analysis
│       ├── strategy.js            # Edge detection, Kelly sizing, risk mgmt
│       └── bot.js                 # Bot orchestrator (setInterval loop)
├── .github/
│   └── workflows/
│       └── deploy.yml             # GitHub Actions → GitHub Pages
├── server.py                      # (Local) FastAPI server
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py                # Configuration dataclasses
├── backend/
│   ├── kalshi_client.py           # (Local) Kalshi API client
│   ├── sports_data.py             # (Local) Tennis & baseball engines
│   ├── strategy.py                # (Local) Strategy engine
│   └── bot.py                     # (Local) Bot orchestrator
└── frontend/
    └── dist/
        └── index.html             # (Local) Dashboard for FastAPI
```

---

## How It Works

1. **Market Discovery** — scans Kalshi events for tennis and baseball keywords
2. **Data Enrichment** — fetches pitcher stats, team batting, bullpen, recent form from MLB Stats API
3. **Analysis** — applies weighted factor models (7 factors each for tennis and baseball)
4. **Edge Detection** — compares model probability to market price
5. **Position Sizing** — fractional Kelly criterion with risk caps
6. **Execution** — places limit orders (live) or logs paper trades (paper mode)
7. **Monitoring** — dashboard shows all signals, analyses, and P&L in real time

---

## Security Notes

- **No server** — the GitHub Pages version has zero backend. Your API keys never leave the browser.
- **Web Crypto API** — RSA-PSS signing happens via the browser's native crypto, not a JS library.
- **localStorage** — config and trading state are persisted locally. Credentials are held in memory only and cleared on page refresh.
- **CORS** — Kalshi's API supports browser requests. MLB Stats API is fully public.

---

## Risk Disclaimer

This bot trades real money on Kalshi when in live mode. Use at your own risk. Start with the demo environment and paper trading. The model's probability estimates are not guaranteed to be accurate. Past performance does not predict future results.
