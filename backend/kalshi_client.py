"""
Kalshi API Client — handles authentication, market discovery, and order execution.
Uses RSA-PSS signing per Kalshi's API spec.
"""
import base64
import datetime
import json
import time
import uuid
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


class KalshiClient:
    """Authenticated client for the Kalshi trading API."""

    def __init__(self, api_key_id: str, private_key_path: str, base_url: str):
        self.api_key_id = api_key_id
        self.base_url = base_url.rstrip("/")
        self._private_key = self._load_private_key(private_key_path) if private_key_path else None
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def _load_private_key(self, path: str) -> rsa.RSAPrivateKey:
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )

    def _sign(self, message: str) -> str:
        signature = self._private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _auth_headers(self, method: str, path: str) -> Dict[str, str]:
        ts = str(int(datetime.datetime.now().timestamp() * 1000))
        path_no_query = path.split("?")[0]
        sig = self._sign(ts + method.upper() + path_no_query)
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def _get(self, path: str, params: Optional[Dict] = None, auth: bool = False) -> Dict:
        url = self.base_url + path
        headers = self._auth_headers("GET", path) if auth and self._private_key else {}
        resp = self._session.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: Dict, auth: bool = True) -> Dict:
        url = self.base_url + path
        headers = self._auth_headers("POST", path) if auth and self._private_key else {}
        resp = self._session.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str, auth: bool = True) -> Dict:
        url = self.base_url + path
        headers = self._auth_headers("DELETE", path) if auth and self._private_key else {}
        resp = self._session.delete(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── Market Discovery ──────────────────────────────────────────────

    def get_events(
        self,
        status: str = "open",
        series_ticker: Optional[str] = None,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> Dict:
        """List events, optionally filtered by series."""
        params = {"status": status, "limit": limit, "with_nested_markets": "true"}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/events", params=params)

    def get_event(self, event_ticker: str) -> Dict:
        return self._get(f"/events/{event_ticker}", params={"with_nested_markets": "true"})

    def get_markets(
        self,
        status: str = "open",
        series_ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> Dict:
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params=params)

    def get_market(self, ticker: str) -> Dict:
        return self._get(f"/markets/{ticker}")

    def get_orderbook(self, ticker: str) -> Dict:
        return self._get(f"/markets/{ticker}/orderbook")

    def get_series(self, series_ticker: str) -> Dict:
        return self._get(f"/series/{series_ticker}")

    # ── Sports Market Discovery ───────────────────────────────────────

    def find_sports_markets(self, sport_keywords: List[str]) -> List[Dict]:
        """
        Scan all open events/markets and filter for sports-related ones.
        Kalshi doesn't have a direct category filter in the API,
        so we keyword-match on titles.
        """
        all_markets = []
        cursor = None
        while True:
            data = self.get_events(status="open", limit=200, cursor=cursor)
            events = data.get("events", [])
            for event in events:
                title_lower = event.get("title", "").lower()
                sub_lower = event.get("sub_title", "").lower()
                category = event.get("category", "").lower()
                combined = f"{title_lower} {sub_lower} {category}"
                if any(kw.lower() in combined for kw in sport_keywords):
                    markets = event.get("markets", [])
                    for m in markets:
                        m["_event_title"] = event.get("title", "")
                        m["_event_category"] = event.get("category", "")
                    all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or not events:
                break
        return all_markets

    def find_tennis_markets(self) -> List[Dict]:
        keywords = [
            "tennis", "ATP", "WTA", "Grand Slam", "Roland Garros",
            "Wimbledon", "US Open Tennis", "Australian Open Tennis",
            "French Open", "match winner", "set winner",
        ]
        return self.find_sports_markets(keywords)

    def find_baseball_markets(self) -> List[Dict]:
        keywords = [
            "baseball", "MLB", "World Series", "American League",
            "National League", "home run", "innings", "pitcher",
            "Yankees", "Dodgers", "Mets", "Red Sox", "Cubs",
            "Astros", "Braves", "Phillies", "Padres",
        ]
        return self.find_sports_markets(keywords)

    # ── Portfolio ─────────────────────────────────────────────────────

    def get_balance(self) -> Dict:
        return self._get("/portfolio/balance", auth=True)

    def get_positions(self, settlement_status: str = "unsettled") -> Dict:
        return self._get(
            "/portfolio/positions",
            params={"settlement_status": settlement_status},
            auth=True,
        )

    def get_fills(self, limit: int = 100) -> Dict:
        return self._get("/portfolio/fills", params={"limit": limit}, auth=True)

    # ── Order Execution ───────────────────────────────────────────────

    def create_order(
        self,
        ticker: str,
        side: str,          # "yes" or "no"
        action: str,         # "buy" or "sell"
        count: int,          # number of contracts
        price_cents: int,    # limit price in cents (1-99)
        time_in_force: str = "gtc",  # "gtc", "ioc", "fill_or_kill"
    ) -> Dict:
        """Place a limit order on Kalshi."""
        order_data = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": "limit",
            "client_order_id": str(uuid.uuid4()),
            "time_in_force": time_in_force,
        }
        if side == "yes":
            order_data["yes_price"] = price_cents
        else:
            order_data["no_price"] = price_cents
        
        logger.info(f"Placing order: {action} {count}x {side} @ {price_cents}¢ on {ticker}")
        return self._post("/portfolio/orders", order_data)

    def cancel_order(self, order_id: str) -> Dict:
        return self._delete(f"/portfolio/orders/{order_id}")

    def get_orders(self, status: str = "resting") -> Dict:
        return self._get("/portfolio/orders", params={"status": status}, auth=True)


class KalshiPublicClient:
    """Unauthenticated client for public market data only."""

    BASE = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self):
        self._session = requests.Session()

    def get_markets(self, **params) -> Dict:
        resp = self._session.get(f"{self.BASE}/markets", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_events(self, **params) -> Dict:
        params.setdefault("with_nested_markets", "true")
        resp = self._session.get(f"{self.BASE}/events", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_orderbook(self, ticker: str) -> Dict:
        resp = self._session.get(f"{self.BASE}/markets/{ticker}/orderbook", timeout=15)
        resp.raise_for_status()
        return resp.json()
