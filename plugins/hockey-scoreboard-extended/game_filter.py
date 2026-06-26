"""
Game filtering and sorting for hockey-scoreboard-extended.

Works on the normalised renderer dicts produced by _ht_to_renderer() in
manager.py, not raw HockeyTech dicts.
"""

import logging
from datetime import datetime
from typing import Dict, List


class HockeyGameFilter:

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_and_sort(
        self,
        games: List[Dict],
        mode_type: str,
        league_cfg: Dict,
    ) -> List[Dict]:
        """
        Apply favourite filtering, state filtering, sorting, and game-count
        limits in one call.

        Args:
            games:      Normalised renderer dicts (from _ht_to_renderer)
            mode_type:  "live", "recent", or "upcoming"
            league_cfg: Merged config dict for the active league
        """
        # 1. Optionally restrict to favourite teams only
        if league_cfg.get("favorite_teams_only", False):
            games = self._filter_favorites_only(games, league_cfg.get("favorite_teams", []))

        # 2. Sort: live > favourites > time
        games = self._sort(games, mode_type, league_cfg.get("favorite_teams", []))

        # 3. Cap at configured limit
        limit_key = {
            "live":     "live_games_to_show",
            "recent":   "recent_games_to_show",
            "upcoming": "upcoming_games_to_show",
        }.get(mode_type)
        defaults = {"live": 10, "recent": 5, "upcoming": 10}
        limit = int(league_cfg.get(limit_key, defaults.get(mode_type, 10)))
        return games[:limit]

    def has_live_games(self, games: List[Dict]) -> bool:
        return any(g.get("status", {}).get("state") == "in" for g in games)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filter_favorites_only(
        self, games: List[Dict], favorites: List[str]
    ) -> List[Dict]:
        if not favorites:
            return games
        favs = {f.upper() for f in favorites}
        return [
            g for g in games
            if g.get("home_team", {}).get("abbrev", "").upper() in favs
            or g.get("away_team", {}).get("abbrev", "").upper() in favs
        ]

    def _is_favorite(self, game: Dict, favorites: List[str]) -> bool:
        favs = {f.upper() for f in favorites}
        home = game.get("home_team", {}).get("abbrev", "").upper()
        away = game.get("away_team", {}).get("abbrev", "").upper()
        return home in favs or away in favs

    def _sort(
        self, games: List[Dict], mode_type: str, favorites: List[str]
    ) -> List[Dict]:
        def key(g):
            state = g.get("status", {}).get("state", "")
            is_live = 0 if state == "in" else 1
            is_fav  = 0 if self._is_favorite(g, favorites) else 1
            start   = g.get("start_time", "")
            try:
                ts = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
                # Most-recent first for recent games, soonest-first for others
                time_score = -ts if mode_type == "recent" else ts
            except (ValueError, TypeError):
                time_score = 0
            return (is_live, is_fav, time_score)

        return sorted(games, key=key)
