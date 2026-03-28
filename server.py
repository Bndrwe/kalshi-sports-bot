"""
FastAPI server — serves the dashboard and provides REST API for the bot.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional

from config.settings import load_config
from backend.bot import TradingBot

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "data" / "bot.log"),
    ]
)
logger = logging.getLogger(__name__)

# Init
app = FastAPI(title="Kalshi Sports Trading Bot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data dir
(Path(__file__).parent / "data").mkdir(exist_ok=True)

# Bot instance
config = load_config()
bot = TradingBot(config)
bot_task: Optional[asyncio.Task] = None


# ── Models ────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    min_edge: Optional[float] = None
    min_confidence: Optional[float] = None
    max_position: Optional[float] = None
    max_daily_loss: Optional[float] = None
    kelly_fraction: Optional[float] = None
    scan_interval: Optional[int] = None

class ModeUpdate(BaseModel):
    mode: str  # "paper" or "live"

class CredentialsUpdate(BaseModel):
    api_key_id: str
    private_key_pem: str
    use_demo: bool = True


# ── API Routes ────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """Get full bot status."""
    return bot.get_state()

@app.post("/api/scan")
async def trigger_scan():
    """Manually trigger a scan cycle."""
    result = await bot.run_scan()
    return result

@app.post("/api/start")
async def start_bot():
    """Start the automated scanning loop."""
    global bot_task
    if bot._running:
        return {"status": "already_running"}
    bot_task = asyncio.create_task(bot.run())
    return {"status": "started", "mode": bot._mode}

@app.post("/api/stop")
async def stop_bot():
    """Stop the scanning loop."""
    bot.stop()
    if bot_task:
        bot_task.cancel()
    return {"status": "stopped"}

@app.post("/api/mode")
async def set_mode(update: ModeUpdate):
    """Switch between paper and live trading."""
    if update.mode not in ("paper", "live"):
        raise HTTPException(400, "Mode must be 'paper' or 'live'")
    bot.set_mode(update.mode)
    return {"mode": bot._mode}

@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    """Update trading parameters."""
    updates = {k: v for k, v in update.dict().items() if v is not None}
    bot.update_config(updates)
    return {"status": "updated", "config": bot.get_state()["config"]}

@app.post("/api/credentials")
async def set_credentials(creds: CredentialsUpdate):
    """Set Kalshi API credentials at runtime."""
    try:
        key_path = Path(__file__).parent / "data" / "kalshi_key.pem"
        key_path.write_text(creds.private_key_pem)
        
        from backend.kalshi_client import KalshiClient
        base_url = config.kalshi.demo_url if creds.use_demo else config.kalshi.base_url
        bot.kalshi = KalshiClient(
            api_key_id=creds.api_key_id,
            private_key_path=str(key_path),
            base_url=base_url,
        )
        config.kalshi.api_key_id = creds.api_key_id
        config.kalshi.private_key_path = str(key_path)
        config.kalshi.use_demo = creds.use_demo

        # Test connection
        balance = bot.kalshi.get_balance()
        
        return {
            "status": "connected",
            "balance_cents": balance.get("balance", 0),
            "portfolio_value_cents": balance.get("portfolio_value", 0),
        }
    except Exception as e:
        raise HTTPException(400, f"Connection failed: {str(e)}")

@app.get("/api/signals")
async def get_signals(sport: Optional[str] = None, limit: int = 50):
    """Get trade signal history."""
    signals = bot._signals[-limit:]
    if sport:
        signals = [s for s in signals if s.sport == sport]
    return {"signals": [s.to_dict() for s in signals]}

@app.get("/api/markets/tennis")
async def get_tennis_markets():
    """Get current tennis markets from Kalshi."""
    try:
        if bot.is_authenticated:
            markets = bot.kalshi.find_tennis_markets()
        else:
            data = bot.kalshi_public.get_events(status="open", limit=200)
            markets = []
            for event in data.get("events", []):
                title = (event.get("title", "") + " " + event.get("category", "")).lower()
                if any(kw in title for kw in ["tennis", "atp", "wta"]):
                    for m in event.get("markets", []):
                        m["_event_title"] = event.get("title", "")
                        markets.append(m)
        return {"markets": markets, "count": len(markets)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/markets/baseball")
async def get_baseball_markets():
    """Get current baseball markets from Kalshi."""
    try:
        if bot.is_authenticated:
            markets = bot.kalshi.find_baseball_markets()
        else:
            data = bot.kalshi_public.get_events(status="open", limit=200)
            markets = []
            for event in data.get("events", []):
                title = (event.get("title", "") + " " + event.get("category", "")).lower()
                if any(kw in title for kw in ["baseball", "mlb"]):
                    for m in event.get("markets", []):
                        m["_event_title"] = event.get("title", "")
                        markets.append(m)
        return {"markets": markets, "count": len(markets)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/mlb/schedule")
async def get_mlb_schedule():
    """Get today's MLB schedule with analysis."""
    games = bot.baseball.get_schedule()
    analyzed = []
    for game in games:
        try:
            analysis = bot.baseball.analyze_game(game)
            analyzed.append({**game, "analysis": analysis})
        except Exception as e:
            analyzed.append({**game, "analysis": None, "error": str(e)})
    return {"games": analyzed, "count": len(analyzed)}

@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """Get recent bot logs."""
    log_file = Path(__file__).parent / "data" / "bot.log"
    if not log_file.exists():
        return {"logs": []}
    lines = log_file.read_text().strip().split("\n")
    return {"logs": lines[-limit:]}

@app.get("/api/scan-history")
async def get_scan_history(limit: int = 50):
    """Get scan history."""
    log_file = Path(__file__).parent / "data" / "scan_history.jsonl"
    if not log_file.exists():
        return {"history": []}
    lines = log_file.read_text().strip().split("\n")
    history = []
    for line in lines[-limit:]:
        try:
            history.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return {"history": history}


# ── Static Files (Dashboard) ─────────────────────────────────────────

frontend_dir = Path(__file__).parent / "frontend" / "dist"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="assets")

@app.get("/{path:path}")
async def serve_frontend(path: str):
    """Serve the dashboard SPA."""
    if frontend_dir.exists():
        file_path = frontend_dir / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dir / "index.html")
    return JSONResponse({"message": "Dashboard not built. Run: cd frontend && npm run build"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
