"""
Data source clients for PWHL and OHL via the HockeyTech platform.

Both leagues use lscluster.hockeytech.com with league-specific credentials.
Credentials were sourced from each league's public web client (network traffic).

HockeyTech GameStatus codes:
  "1" = Scheduled (shows time in GameStatusString, e.g. "7:05PM")
  "2" = In progress (period 1 or 2)
  "3" = In progress (period 3 / OT / shootout)
  "4" = Final

If credentials stop working, capture a request from the league website in
browser DevTools → Network tab → filter for lscluster.hockeytech.com.
"""

import logging
from datetime import timedelta
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_HEADERS = {"User-Agent": "LEDMatrix/1.0", "Accept": "application/json"}

_LIVE_STATUSES = {"2", "3"}
_FINAL_STATUSES = {"4"}
_UPCOMING_STATUSES = {"1"}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class HockeyTechDataSource:
    """
    Generic HockeyTech API client.
    Instantiate via the PWHL or OHL subclasses.

    Game dict keys of interest:
        HomeCode, VisitorCode          — team abbreviations
        HomeLongName, VisitorLongName  — full team names
        HomeGoals, VisitorGoals        — score (strings)
        GameStatus                     — "1"=upcoming "2"/"3"=live "4"=final
        GameStatusString               — human-readable status / scheduled time
        Period, PeriodNameLong         — current period e.g. "3rd", "OT"
        GameClock                      — MM:SS remaining
        GameDateISO8601                — ISO 8601 start time with tz offset
        venue_name, venue_location
        HomeLogo, VisitorLogo          — logo URLs
    """

    BASE_URL = "https://lscluster.hockeytech.com/feed/"
    API_KEY: str
    CLIENT_CODE: str

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.session = _make_session()

    def _scorebar(self, days_back: int = 1, days_ahead: int = 1) -> List[Dict]:
        params = {
            "feed": "modulekit",
            "view": "scorebar",
            "key": self.API_KEY,
            "client_code": self.CLIENT_CODE,
            "site_id": "0",
            "league_id": "0",
            "lang": "en",
            "numberofdaysback": str(days_back),
            "numberofdaysahead": str(days_ahead),
        }
        try:
            resp = self.session.get(self.BASE_URL, headers=_HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json().get("SiteKit", {}).get("Scorebar", [])
        except Exception as e:
            self.logger.error(f"{self.CLIENT_CODE.upper()} HockeyTech error: {e}")
            return []

    def fetch_live_games(self) -> List[Dict]:
        games = self._scorebar(days_back=0, days_ahead=0)
        live = [g for g in games if g.get("GameStatus") in _LIVE_STATUSES]
        self.logger.debug(f"{self.CLIENT_CODE.upper()}: {len(live)} live games")
        return live

    def fetch_recent_games(self, days_back: int = 2) -> List[Dict]:
        games = self._scorebar(days_back=days_back, days_ahead=0)
        recent = [g for g in games if g.get("GameStatus") in _FINAL_STATUSES]
        self.logger.debug(f"{self.CLIENT_CODE.upper()}: {len(recent)} recent games")
        return recent

    def fetch_upcoming_games(self, days_ahead: int = 3) -> List[Dict]:
        games = self._scorebar(days_back=0, days_ahead=days_ahead)
        upcoming = [g for g in games if g.get("GameStatus") in _UPCOMING_STATUSES]
        self.logger.debug(f"{self.CLIENT_CODE.upper()}: {len(upcoming)} upcoming games")
        return upcoming


class PWHLDataSource(HockeyTechDataSource):
    # Key sourced from thepwhl.com network traffic.
    API_KEY = "446521baf8c38984"
    CLIENT_CODE = "pwhl"


class OHLDataSource(HockeyTechDataSource):
    # Key sourced from ontariohockeyleague.com network traffic.
    API_KEY = "f1aa699db3d81487"
    CLIENT_CODE = "ohl"
