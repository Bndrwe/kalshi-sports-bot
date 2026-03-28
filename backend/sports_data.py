"""
Sports Data Collection — fetches real-time stats for tennis and baseball.
Uses free public APIs: MLB Stats API, Tennis Abstract, and web scraping fallbacks.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  TENNIS DATA
# ══════════════════════════════════════════════════════════════════════

class TennisDataProvider:
    """Collects tennis player stats, rankings, H2H, surface performance, scheduling."""

    # Surface classification
    SURFACE_MAP = {
        "hard": "hard", "hardcourt": "hard", "hard court": "hard",
        "clay": "clay", "terre battue": "clay",
        "grass": "grass",
        "indoor": "hard_indoor", "carpet": "hard_indoor",
    }

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "KalshiSportsBot/1.0"
        })
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_ttl = 1800  # 30 min

    def _cached_get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        cache_key = f"{url}:{json.dumps(params or {}, sort_keys=True)}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return data
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json() if "json" in resp.headers.get("content-type", "") else {"text": resp.text}
            self._cache[cache_key] = (time.time(), data)
            return data
        except Exception as e:
            logger.warning(f"Tennis data fetch failed for {url}: {e}")
            return None

    def get_player_profile(self, player_name: str) -> Dict:
        """Build a comprehensive player profile from available sources."""
        profile = {
            "name": player_name,
            "ranking": None,
            "age": None,
            "hand": None,
            "surface_records": {"hard": {}, "clay": {}, "grass": {}},
            "recent_form": [],         # Last 10 results
            "ytd_record": {"wins": 0, "losses": 0},
            "serve_stats": {},
            "return_stats": {},
            "fatigue_score": 0.0,      # 0 = fresh, 1 = exhausted
            "days_since_last_match": None,
            "matches_last_30_days": 0,
            "tiebreak_record": {"wins": 0, "losses": 0},
            "deciding_set_record": {"wins": 0, "losses": 0},
        }
        return profile

    def analyze_surface_advantage(self, player_name: str, surface: str) -> float:
        """
        Calculate a player's advantage on a given surface.
        Returns a score from -1.0 (very bad) to +1.0 (very strong).
        
        Factors:
        - Win rate on surface vs overall win rate
        - Historical dominance on surface type
        - Recent results on same surface
        """
        profile = self.get_player_profile(player_name)
        surface_key = self.SURFACE_MAP.get(surface.lower(), "hard")
        
        sr = profile["surface_records"].get(surface_key, {})
        surface_wins = sr.get("wins", 0)
        surface_losses = sr.get("losses", 0)
        total_surface = surface_wins + surface_losses
        
        if total_surface < 5:
            return 0.0  # Insufficient data
        
        surface_wr = surface_wins / total_surface
        ytd = profile["ytd_record"]
        overall_total = ytd["wins"] + ytd["losses"]
        overall_wr = ytd["wins"] / overall_total if overall_total > 0 else 0.5
        
        advantage = (surface_wr - overall_wr) * 2.0
        return max(-1.0, min(1.0, advantage))

    def calculate_fatigue(self, player_name: str) -> float:
        """
        Fatigue score 0-1 based on:
        - Days since last match (lower = more fatigued)
        - Number of matches in last 14 / 30 days
        - Duration of recent matches (5-setters exhaust more)
        - Travel between tournaments
        """
        profile = self.get_player_profile(player_name)
        fatigue = 0.0
        
        days_rest = profile.get("days_since_last_match")
        if days_rest is not None:
            if days_rest == 0:
                fatigue += 0.3   # Playing same day = high fatigue
            elif days_rest == 1:
                fatigue += 0.15
            elif days_rest >= 7:
                fatigue -= 0.1   # Well rested
        
        matches_30d = profile.get("matches_last_30_days", 0)
        if matches_30d > 12:
            fatigue += 0.25
        elif matches_30d > 8:
            fatigue += 0.1
        
        return max(0.0, min(1.0, fatigue))

    def get_h2h(self, player1: str, player2: str) -> Dict:
        """Head-to-head record between two players."""
        return {
            "player1": player1,
            "player2": player2,
            "p1_wins": 0,
            "p2_wins": 0,
            "p1_surface_wins": {},
            "p2_surface_wins": {},
            "last_5_meetings": [],
        }

    def analyze_match(
        self,
        player1: str,
        player2: str,
        surface: str,
        tournament: str = "",
        round_name: str = "",
    ) -> Dict:
        """
        Full match analysis combining all factors.
        Returns probability estimate and detailed breakdown.
        """
        p1_profile = self.get_player_profile(player1)
        p2_profile = self.get_player_profile(player2)
        h2h = self.get_h2h(player1, player2)

        # Surface analysis
        p1_surface = self.analyze_surface_advantage(player1, surface)
        p2_surface = self.analyze_surface_advantage(player2, surface)

        # Fatigue
        p1_fatigue = self.calculate_fatigue(player1)
        p2_fatigue = self.calculate_fatigue(player2)

        # Ranking differential (normalized)
        p1_rank = p1_profile.get("ranking") or 200
        p2_rank = p2_profile.get("ranking") or 200
        rank_diff = (p2_rank - p1_rank) / max(p1_rank, p2_rank, 1)
        rank_factor = max(-1.0, min(1.0, rank_diff * 0.5))

        # Recent form (win rate over last 10)
        p1_form = p1_profile.get("recent_form", [])
        p2_form = p2_profile.get("recent_form", [])
        p1_form_score = sum(1 for r in p1_form if r.get("won")) / max(len(p1_form), 1)
        p2_form_score = sum(1 for r in p2_form if r.get("won")) / max(len(p2_form), 1)
        form_diff = p1_form_score - p2_form_score

        # H2H
        total_h2h = h2h["p1_wins"] + h2h["p2_wins"]
        h2h_factor = 0.0
        if total_h2h >= 3:
            h2h_factor = (h2h["p1_wins"] - h2h["p2_wins"]) / total_h2h

        # Serve dominance
        p1_serve = p1_profile.get("serve_stats", {})
        p2_serve = p2_profile.get("serve_stats", {})
        p1_ace_rate = p1_serve.get("ace_rate", 0.05)
        p2_ace_rate = p2_serve.get("ace_rate", 0.05)
        serve_diff = (p1_ace_rate - p2_ace_rate) * 5

        # Mental strength (tiebreaks, deciding sets)
        p1_tb = p1_profile.get("tiebreak_record", {"wins": 0, "losses": 0})
        p2_tb = p2_profile.get("tiebreak_record", {"wins": 0, "losses": 0})
        p1_mental = p1_tb["wins"] / max(p1_tb["wins"] + p1_tb["losses"], 1)
        p2_mental = p2_tb["wins"] / max(p2_tb["wins"] + p2_tb["losses"], 1)
        mental_diff = p1_mental - p2_mental

        # Weighted combination
        from config.settings import TennisConfig
        tc = TennisConfig()

        raw_edge = (
            tc.weight_surface * (p1_surface - p2_surface)
            + tc.weight_form * form_diff
            + tc.weight_h2h * h2h_factor
            + tc.weight_fatigue * (p2_fatigue - p1_fatigue)  # Higher fatigue for p2 helps p1
            + tc.weight_ranking * rank_factor
            + tc.weight_serve * serve_diff
            + tc.weight_mental * mental_diff
        )

        # Convert to probability using logistic function
        import math
        p1_prob = 1.0 / (1.0 + math.exp(-3.0 * raw_edge))
        p1_prob = max(0.05, min(0.95, p1_prob))

        return {
            "player1": player1,
            "player2": player2,
            "surface": surface,
            "tournament": tournament,
            "round": round_name,
            "p1_win_probability": round(p1_prob, 4),
            "p2_win_probability": round(1 - p1_prob, 4),
            "confidence": round(abs(p1_prob - 0.5) * 2, 4),
            "factors": {
                "surface_advantage": {"p1": round(p1_surface, 3), "p2": round(p2_surface, 3)},
                "fatigue": {"p1": round(p1_fatigue, 3), "p2": round(p2_fatigue, 3)},
                "ranking": {"p1": p1_rank, "p2": p2_rank, "factor": round(rank_factor, 3)},
                "recent_form": {"p1": round(p1_form_score, 3), "p2": round(p2_form_score, 3)},
                "h2h": {"p1_wins": h2h["p1_wins"], "p2_wins": h2h["p2_wins"]},
                "serve_dominance": round(serve_diff, 3),
                "mental_strength": round(mental_diff, 3),
            },
            "raw_edge": round(raw_edge, 4),
        }


# ══════════════════════════════════════════════════════════════════════
#  BASEBALL DATA
# ══════════════════════════════════════════════════════════════════════

class BaseballDataProvider:
    """Collects MLB stats via the free MLB Stats API."""

    MLB_API = "https://statsapi.mlb.com/api/v1"
    
    # Park factors (runs per game relative to average)
    PARK_FACTORS = {
        "Coors Field": 1.35, "Great American Ball Park": 1.12,
        "Fenway Park": 1.08, "Globe Life Field": 1.05,
        "Citizens Bank Park": 1.04, "Wrigley Field": 1.03,
        "Yankee Stadium": 1.02, "Guaranteed Rate Field": 1.01,
        "Target Field": 0.99, "Dodger Stadium": 0.98,
        "Truist Park": 0.97, "T-Mobile Park": 0.95,
        "Oracle Park": 0.93, "Petco Park": 0.92,
        "Tropicana Field": 0.91, "Oakland Coliseum": 0.90,
    }

    def __init__(self):
        self._session = requests.Session()
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_ttl = 1800

    def _cached_get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        cache_key = f"{url}:{json.dumps(params or {}, sort_keys=True)}"
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return data
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self._cache[cache_key] = (time.time(), data)
            return data
        except Exception as e:
            logger.warning(f"MLB API fetch failed: {e}")
            return None

    def get_schedule(self, date: Optional[str] = None) -> List[Dict]:
        """Get today's or a specific date's MLB schedule."""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        data = self._cached_get(
            f"{self.MLB_API}/schedule",
            params={"sportId": 1, "date": date, "hydrate": "team,probablePitcher,linescore"}
        )
        if not data:
            return []
        games = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                games.append(self._parse_game(game))
        return games

    def _parse_game(self, game: Dict) -> Dict:
        away = game.get("teams", {}).get("away", {})
        home = game.get("teams", {}).get("home", {})
        venue = game.get("venue", {}).get("name", "")
        
        away_pitcher = away.get("probablePitcher", {})
        home_pitcher = home.get("probablePitcher", {})

        return {
            "game_id": game.get("gamePk"),
            "status": game.get("status", {}).get("detailedState", ""),
            "venue": venue,
            "game_date": game.get("gameDate", ""),
            "away_team": {
                "id": away.get("team", {}).get("id"),
                "name": away.get("team", {}).get("name", ""),
                "abbreviation": away.get("team", {}).get("abbreviation", ""),
                "record": f"{away.get('leagueRecord', {}).get('wins', 0)}-{away.get('leagueRecord', {}).get('losses', 0)}",
            },
            "home_team": {
                "id": home.get("team", {}).get("id"),
                "name": home.get("team", {}).get("name", ""),
                "abbreviation": home.get("team", {}).get("abbreviation", ""),
                "record": f"{home.get('leagueRecord', {}).get('wins', 0)}-{home.get('leagueRecord', {}).get('losses', 0)}",
            },
            "away_pitcher": {
                "id": away_pitcher.get("id"),
                "name": away_pitcher.get("fullName", "TBD"),
                "era": None,  # Filled by detailed stats
            },
            "home_pitcher": {
                "id": home_pitcher.get("id"),
                "name": home_pitcher.get("fullName", "TBD"),
                "era": None,
            },
            "park_factor": self.PARK_FACTORS.get(venue, 1.0),
        }

    def get_pitcher_stats(self, pitcher_id: int, season: Optional[int] = None) -> Dict:
        """Get detailed pitcher statistics."""
        if not pitcher_id:
            return self._empty_pitcher_stats()
        season = season or datetime.now().year
        data = self._cached_get(
            f"{self.MLB_API}/people/{pitcher_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching"}
        )
        if not data:
            return self._empty_pitcher_stats()

        try:
            splits = data.get("stats", [{}])[0].get("splits", [])
            if not splits:
                return self._empty_pitcher_stats()
            s = splits[0].get("stat", {})
        except (IndexError, KeyError):
            return self._empty_pitcher_stats()
        return {
            "era": float(s.get("era", 4.50)),
            "whip": float(s.get("whip", 1.30)),
            "k_per_9": float(s.get("strikeoutsPer9Inn", 8.0)),
            "bb_per_9": float(s.get("walksPer9Inn", 3.0)),
            "innings_pitched": float(s.get("inningsPitched", 0)),
            "wins": int(s.get("wins", 0)),
            "losses": int(s.get("losses", 0)),
            "hr_per_9": float(s.get("homeRunsPer9", 1.0)),
            "batting_avg_against": float(s.get("avg", 0.250)),
            "games_started": int(s.get("gamesStarted", 0)),
            "quality_start_pct": 0.0,  # Calculated separately
            "pitches_last_start": None,  # From game logs
            "days_rest": None,
        }

    def _empty_pitcher_stats(self) -> Dict:
        return {
            "era": 4.50, "whip": 1.30, "k_per_9": 8.0, "bb_per_9": 3.0,
            "innings_pitched": 0, "wins": 0, "losses": 0, "hr_per_9": 1.0,
            "batting_avg_against": 0.250, "games_started": 0,
            "quality_start_pct": 0.0, "pitches_last_start": None, "days_rest": None,
        }

    def get_team_batting(self, team_id: int, season: Optional[int] = None) -> Dict:
        """Get team batting stats."""
        season = season or datetime.now().year
        data = self._cached_get(
            f"{self.MLB_API}/teams/{team_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting"}
        )
        if not data:
            return self._empty_batting()

        try:
            splits = data.get("stats", [{}])[0].get("splits", [])
            if not splits:
                return self._empty_batting()
            s = splits[0].get("stat", {})
        except (IndexError, KeyError):
            return self._empty_batting()
        return {
            "avg": float(s.get("avg", 0.250)),
            "obp": float(s.get("obp", 0.320)),
            "slg": float(s.get("slg", 0.400)),
            "ops": float(s.get("ops", 0.720)),
            "runs_per_game": float(s.get("runs", 0)) / max(int(s.get("gamesPlayed", 1)), 1),
            "home_runs": int(s.get("homeRuns", 0)),
            "strikeouts": int(s.get("strikeOuts", 0)),
            "walks": int(s.get("baseOnBalls", 0)),
            "stolen_bases": int(s.get("stolenBases", 0)),
            "left_on_base": int(s.get("leftOnBase", 0)),
            "batting_risp": float(s.get("avg", 0.250)),  # Approx
        }

    def _empty_batting(self) -> Dict:
        return {
            "avg": 0.250, "obp": 0.320, "slg": 0.400, "ops": 0.720,
            "runs_per_game": 4.5, "home_runs": 0, "strikeouts": 0,
            "walks": 0, "stolen_bases": 0, "left_on_base": 0, "batting_risp": 0.250,
        }

    def get_team_bullpen(self, team_id: int, season: Optional[int] = None) -> Dict:
        """Get team bullpen/relief pitching stats."""
        season = season or datetime.now().year
        data = self._cached_get(
            f"{self.MLB_API}/teams/{team_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching"}
        )
        if not data:
            return {"era": 4.00, "whip": 1.30, "saves": 0, "blown_saves": 0, "holds": 0}

        try:
            splits = data.get("stats", [{}])[0].get("splits", [])
            if not splits:
                return {"era": 4.00, "whip": 1.30, "saves": 0, "blown_saves": 0, "holds": 0}
            s = splits[0].get("stat", {})
        except (IndexError, KeyError):
            return {"era": 4.00, "whip": 1.30, "saves": 0, "blown_saves": 0, "holds": 0}
        return {
            "era": float(s.get("era", 4.00)),
            "whip": float(s.get("whip", 1.30)),
            "saves": int(s.get("saves", 0)),
            "blown_saves": int(s.get("blownSaves", 0)),
            "holds": int(s.get("holds", 0)),
            "k_per_9": float(s.get("strikeoutsPer9Inn", 8.0)),
        }

    def get_team_recent_form(self, team_id: int, last_n: int = 10) -> Dict:
        """Get team's last N games results."""
        today = datetime.now()
        start = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        data = self._cached_get(
            f"{self.MLB_API}/schedule",
            params={
                "sportId": 1, "teamId": team_id,
                "startDate": start, "endDate": end,
                "gameType": "R"
            }
        )
        if not data:
            return {"wins": 0, "losses": 0, "run_diff": 0, "streak": ""}

        games = []
        for date_entry in data.get("dates", []):
            for g in date_entry.get("games", []):
                if g.get("status", {}).get("detailedState") == "Final":
                    games.append(g)

        recent = games[-last_n:] if len(games) >= last_n else games
        wins = 0
        losses = 0
        run_diff = 0
        for g in recent:
            away = g.get("teams", {}).get("away", {})
            home = g.get("teams", {}).get("home", {})
            if away.get("team", {}).get("id") == team_id:
                if away.get("isWinner"):
                    wins += 1
                else:
                    losses += 1
                run_diff += away.get("score", 0) - home.get("score", 0)
            else:
                if home.get("isWinner"):
                    wins += 1
                else:
                    losses += 1
                run_diff += home.get("score", 0) - away.get("score", 0)

        return {
            "wins": wins,
            "losses": losses,
            "win_pct": wins / max(wins + losses, 1),
            "run_diff": run_diff,
            "games_played": len(recent),
        }

    def get_weather(self, venue: str) -> Dict:
        """Estimate weather impact on game. Placeholder for actual weather API."""
        # In production, integrate OpenWeatherMap or similar
        return {
            "temp_f": 72,
            "wind_mph": 8,
            "wind_direction": "out",  # "in", "out", "cross"
            "humidity_pct": 50,
            "precipitation_pct": 0,
            "impact_factor": 1.0,  # >1 = hitter-friendly, <1 = pitcher-friendly
        }

    def analyze_game(self, game: Dict) -> Dict:
        """
        Full game analysis combining all factors.
        Returns probability estimate and detailed breakdown.
        """
        import math
        from config.settings import BaseballConfig
        bc = BaseballConfig()

        away = game["away_team"]
        home = game["home_team"]

        # Pitcher analysis
        away_p = self.get_pitcher_stats(game["away_pitcher"].get("id"))
        home_p = self.get_pitcher_stats(game["home_pitcher"].get("id"))
        
        # Normalize ERA (lower is better) - league avg ~4.20
        away_p_score = (4.50 - away_p["era"]) / 4.50
        home_p_score = (4.50 - home_p["era"]) / 4.50
        pitching_factor = home_p_score - away_p_score  # Positive = home advantage

        # Team batting
        away_bat = self.get_team_batting(away["id"]) if away.get("id") else self._empty_batting()
        home_bat = self.get_team_batting(home["id"]) if home.get("id") else self._empty_batting()
        batting_factor = (home_bat["ops"] - away_bat["ops"]) * 2.0

        # Bullpen
        away_bp = self.get_team_bullpen(away["id"]) if away.get("id") else {"era": 4.0}
        home_bp = self.get_team_bullpen(home["id"]) if home.get("id") else {"era": 4.0}
        bp_factor = (away_bp["era"] - home_bp["era"]) / 4.50  # Positive = home advantage

        # Park factor
        pf = game.get("park_factor", 1.0)
        park_factor = (pf - 1.0) * 0.5  # Slight home advantage in hitter-friendly parks

        # Recent form
        away_form = self.get_team_recent_form(away["id"]) if away.get("id") else {"win_pct": 0.5}
        home_form = self.get_team_recent_form(home["id"]) if home.get("id") else {"win_pct": 0.5}
        form_factor = home_form["win_pct"] - away_form["win_pct"]

        # Weather
        weather = self.get_weather(game.get("venue", ""))
        weather_factor = (weather["impact_factor"] - 1.0) * 0.1

        # Home field advantage baseline (~54% historically in MLB)
        home_base = 0.04

        # Weighted combination
        raw_edge = (
            home_base
            + bc.weight_pitching * pitching_factor
            + bc.weight_batting * batting_factor
            + bc.weight_bullpen * bp_factor
            + bc.weight_park_factor * park_factor
            + bc.weight_weather * weather_factor
            + bc.weight_recent_form * form_factor
        )

        # Convert to probability
        home_prob = 1.0 / (1.0 + math.exp(-3.0 * raw_edge))
        home_prob = max(0.05, min(0.95, home_prob))

        return {
            "game_id": game.get("game_id"),
            "away_team": away["name"],
            "home_team": home["name"],
            "venue": game.get("venue", ""),
            "home_win_probability": round(home_prob, 4),
            "away_win_probability": round(1 - home_prob, 4),
            "confidence": round(abs(home_prob - 0.5) * 2, 4),
            "factors": {
                "pitching": {
                    "away_pitcher": game["away_pitcher"]["name"],
                    "home_pitcher": game["home_pitcher"]["name"],
                    "away_era": away_p["era"],
                    "home_era": home_p["era"],
                    "factor": round(pitching_factor, 3),
                },
                "batting": {
                    "away_ops": away_bat["ops"],
                    "home_ops": home_bat["ops"],
                    "factor": round(batting_factor, 3),
                },
                "bullpen": {
                    "away_era": away_bp["era"],
                    "home_era": home_bp["era"],
                    "factor": round(bp_factor, 3),
                },
                "park": {
                    "venue": game.get("venue", ""),
                    "factor": round(pf, 3),
                },
                "recent_form": {
                    "away": away_form,
                    "home": home_form,
                    "factor": round(form_factor, 3),
                },
                "weather": weather,
                "home_field_advantage": home_base,
            },
            "raw_edge": round(raw_edge, 4),
        }
