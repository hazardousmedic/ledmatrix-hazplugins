"""
HockeyScoreboardExtendedPlugin — entry point for LEDMatrix.

Covers PWHL and OHL; deliberately excludes NHL, NCAA Men's, and NCAA Women's
hockey which are handled by the official hockey-scoreboard plugin.
"""

import logging
from typing import Any, Dict, List, Optional

from data_sources import OHLDataSource, PWHLDataSource
from game_filter import HockeyGameFilter
from game_renderer import GameRenderer
from logo_downloader import ensure_logos


# HockeyTech GameStatus codes
_STATUS_LIVE = {"2", "3"}
_STATUS_FINAL = {"4"}
_STATUS_UPCOMING = {"1"}


def _ht_to_renderer(game: Dict, league: str) -> Dict:
    """
    Convert a HockeyTech scorebar game dict into the shape GameRenderer expects.

    HockeyTech source fields:
        HomeCode / VisitorCode        — team abbreviations
        HomeLongName / VisitorLongName
        HomeGoals / VisitorGoals      — score strings
        HomeWins / HomeRegulationLosses / HomeOTLosses / HomeShootoutLosses
        GameStatus                    — "1" upcoming / "2","3" live / "4" final
        GameStatusString              — e.g. "7:05PM" or "Final"
        PeriodNameLong                — e.g. "3rd", "OT"
        GameClock                     — MM:SS remaining
        GameDateISO8601               — ISO 8601 start time with tz
    """
    status_code = str(game.get("GameStatus", "1"))

    if status_code in _STATUS_LIVE:
        state = "in"
        period = game.get("PeriodNameLong", "")
        clock = game.get("GameClock", "")
        short_detail = f"{period} {clock}".strip()
    elif status_code in _STATUS_FINAL:
        state = "post"
        short_detail = "Final"
        period = game.get("PeriodNameLong", "")
        clock = ""
    else:
        state = "pre"
        short_detail = game.get("GameStatusString", "")
        period = ""
        clock = ""

    def record(wins, reg_losses, ot_losses, so_losses):
        losses = int(reg_losses or 0) + int(ot_losses or 0) + int(so_losses or 0)
        return f"{wins}-{losses}"

    return {
        "league": league,
        "home_team": {
            "abbrev": game.get("HomeCode", ""),
            "name": game.get("HomeLongName", ""),
            "score": game.get("HomeGoals", "0"),
            "record": record(
                game.get("HomeWins", 0),
                game.get("HomeRegulationLosses", 0),
                game.get("HomeOTLosses", 0),
                game.get("HomeShootoutLosses", 0),
            ),
        },
        "away_team": {
            "abbrev": game.get("VisitorCode", ""),
            "name": game.get("VisitorLongName", ""),
            "score": game.get("VisitorGoals", "0"),
            "record": record(
                game.get("VisitorWins", 0),
                game.get("VisitorRegulationLosses", 0),
                game.get("VisitorOTLosses", 0),
                game.get("VisitorShootoutLosses", 0),
            ),
        },
        "status": {
            "state": state,
            "short_detail": short_detail,
            "period": period,
            "display_clock": clock,
        },
        "start_time": game.get("GameDateISO8601", ""),
    }


class HockeyScoreboardExtendedPlugin:
    """
    LEDMatrix plugin displaying PWHL and OHL scores.

    Instantiation signature matches what plugin_loader.py passes:
        plugin_id, config, display_manager, cache_manager, plugin_manager

    display_modes (declared in manifest.json):
        pwhl_live / pwhl_recent / pwhl_upcoming
        ohl_live  / ohl_recent  / ohl_upcoming
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager=None,
        plugin_manager=None,
    ):
        self.plugin_id = plugin_id
        self.display_manager = display_manager
        self.logger = logging.getLogger(plugin_id)

        self._apply_config(config)

        self._pwhl = PWHLDataSource(self.logger)
        self._ohl = OHLDataSource(self.logger)
        self._filter = HockeyGameFilter(self.logger)

        self._games: List[Dict] = []
        self._game_index = 0

        # Download any missing logos for the active league at startup
        league = self._active_league()
        try:
            ensure_logos(league)
        except Exception:
            self.logger.warning(f"Logo download failed for {league}, continuing without logos")

        w = getattr(display_manager, "width", 64)
        h = getattr(display_manager, "height", 32)
        self._renderer = GameRenderer(
            display_width=w,
            display_height=h,
            config=self.config,
            custom_logger=self.logger,
        )

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _apply_config(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.display_mode: str = config.get("display_mode", "pwhl_live")

    def _active_league(self) -> str:
        return "pwhl" if self.display_mode.startswith("pwhl") else "ohl"

    def _active_mode_type(self) -> str:
        return self.display_mode.split("_", 1)[1]  # "live" / "recent" / "upcoming"

    def _league_cfg(self) -> Dict[str, Any]:
        """
        Merge defaults → league-specific overrides into one flat dict.
        League block wins over defaults block wins over hardcoded fallbacks.
        """
        defaults = self.config.get("defaults", {})
        league_overrides = self.config.get(self._active_league(), {})
        return {**defaults, **league_overrides}

    # ------------------------------------------------------------------
    # Required plugin interface
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Refresh game data from the API. Called on update_interval schedule."""
        raw = self._fetch()

        league = self._active_league()
        mode_type = self._active_mode_type()
        league_cfg = self._league_cfg()

        # Convert to renderer dicts
        converted = [_ht_to_renderer(g, league) for g in raw]

        # Apply favourite filtering, sorting, and game-count limits
        self._games = self._filter.filter_and_sort(converted, mode_type, league_cfg)
        self._game_index = 0

        self.logger.debug(
            f"{league.upper()} {mode_type}: {len(self._games)} games after filtering"
        )

    def display(self, force_clear: bool = False, display_mode: str = "") -> bool:
        """
        Render one game card to the matrix.
        Returns True if content was shown, False if nothing to show
        (signals LEDMatrix to skip to the next plugin).
        """
        if not self._games:
            return False

        game = self._games[self._game_index]
        success = self._render(game, self._active_mode_type())
        self._game_index = (self._game_index + 1) % len(self._games)
        return success

    def cleanup(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Optional interface — duration & cycle tracking
    # ------------------------------------------------------------------

    def get_display_duration(self) -> float:
        return float(self._league_cfg().get("display_duration", 15))

    def is_cycle_complete(self) -> bool:
        """True once every game in the current list has been shown once."""
        return self._game_index == 0

    # ------------------------------------------------------------------
    # Optional interface — live priority
    # ------------------------------------------------------------------

    def has_live_priority(self) -> bool:
        """Whether this plugin can interrupt the normal rotation for live games."""
        return bool(self._league_cfg().get("live_priority", True))

    def has_live_content(self) -> bool:
        """True if there is currently at least one live game."""
        if not self.has_live_priority():
            return False
        # Check without touching self._games so we don't disrupt the current cycle
        league = self._active_league()
        src = self._pwhl if league == "pwhl" else self._ohl
        try:
            live = src.fetch_live_games()
            return len(live) > 0
        except Exception:
            return False

    def get_live_modes(self) -> List[str]:
        """Display modes to activate during a live-priority takeover."""
        league = self._active_league()
        return [f"{league}_live"]

    # ------------------------------------------------------------------
    # Optional interface — hot-reload
    # ------------------------------------------------------------------

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        prev_league = self._active_league()
        self._apply_config(new_config)
        new_league = self._active_league()

        # Download logos if switching to a league whose logos may not exist yet
        if new_league != prev_league:
            try:
                ensure_logos(new_league)
            except Exception:
                self.logger.warning(f"Logo download failed for {new_league}")

        self._games = []
        self._game_index = 0

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch(self) -> List[Dict]:
        league_cfg = self._league_cfg()
        recent_days = int(league_cfg.get("recent_days", 2))
        upcoming_days = int(league_cfg.get("upcoming_days", 3))

        mode = self.display_mode
        if mode == "pwhl_live":
            return self._pwhl.fetch_live_games()
        if mode == "pwhl_recent":
            return self._pwhl.fetch_recent_games(recent_days)
        if mode == "pwhl_upcoming":
            return self._pwhl.fetch_upcoming_games(upcoming_days)
        if mode == "ohl_live":
            return self._ohl.fetch_live_games()
        if mode == "ohl_recent":
            return self._ohl.fetch_recent_games(recent_days)
        if mode == "ohl_upcoming":
            return self._ohl.fetch_upcoming_games(upcoming_days)

        self.logger.warning(f"Unknown display_mode: {mode}")
        return []

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self, game: Dict, game_type: str) -> bool:
        try:
            image = self._renderer.render_game_card(game, game_type=game_type)
            self.display_manager.image.paste(image, (0, 0))
            self.display_manager.update_display()
            return True
        except Exception:
            self.logger.exception("Error rendering game card")
            return False
