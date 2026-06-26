"""
HockeyScoreboardExtendedPlugin — entry point for LEDMatrix.

Covers PWHL and OHL; deliberately excludes NHL, NCAA Men's, and NCAA Women's
hockey which are handled by the official hockey-scoreboard plugin.

LEDMatrix rotates through every entry in manifest.json display_modes and calls
display(display_mode="pwhl_live") etc. on each turn. update() pre-fetches data
for all modes so each display() call renders instantly from cache.
"""

import logging
from typing import Any, Dict, List, Optional

from data_sources import OHLDataSource, PWHLDataSource
from game_filter import HockeyGameFilter
from game_renderer import GameRenderer
from logo_downloader import ensure_logos

try:
    from src.plugin_system.base_plugin import BasePlugin
except ImportError:
    class BasePlugin:  # type: ignore[no-redef]
        def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
            self.plugin_id = plugin_id
            self.config = config
            self.display_manager = display_manager
            self.cache_manager = cache_manager
            self.plugin_manager = plugin_manager
            self.logger = logging.getLogger(f"plugin.{plugin_id}")
            self.enabled = config.get("enabled", True)


_STATUS_LIVE = {"2", "3"}
_STATUS_FINAL = {"4"}
_STATUS_UPCOMING = {"1"}

_ALL_MODES = [
    "pwhl_live", "pwhl_recent", "pwhl_upcoming",
    "ohl_live",  "ohl_recent",  "ohl_upcoming",
]


def _league_of(mode: str) -> str:
    return "pwhl" if mode.startswith("pwhl") else "ohl"


def _type_of(mode: str) -> str:
    return mode.split("_", 1)[1]  # "live" / "recent" / "upcoming"


def _ht_to_renderer(game: Dict, league: str) -> Dict:
    """Convert a HockeyTech scorebar dict into the shape GameRenderer expects."""
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
            "name":   game.get("HomeLongName", ""),
            "score":  game.get("HomeGoals", "0"),
            "record": record(
                game.get("HomeWins", 0),
                game.get("HomeRegulationLosses", 0),
                game.get("HomeOTLosses", 0),
                game.get("HomeShootoutLosses", 0),
            ),
        },
        "away_team": {
            "abbrev": game.get("VisitorCode", ""),
            "name":   game.get("VisitorLongName", ""),
            "score":  game.get("VisitorGoals", "0"),
            "record": record(
                game.get("VisitorWins", 0),
                game.get("VisitorRegulationLosses", 0),
                game.get("VisitorOTLosses", 0),
                game.get("VisitorShootoutLosses", 0),
            ),
        },
        "status": {
            "state":        state,
            "short_detail": short_detail,
            "period":       period,
            "display_clock": clock,
        },
        "start_time": game.get("GameDateISO8601", ""),
    }


class HockeyScoreboardExtendedPlugin(BasePlugin):
    """
    LEDMatrix plugin displaying PWHL and OHL scores.

    All six display modes rotate automatically — LEDMatrix passes the current
    mode name into display(display_mode=...) on each call. No per-mode config
    selection needed.
    """

    def __init__(
        self,
        plugin_id: str,
        config: Dict[str, Any],
        display_manager,
        cache_manager=None,
        plugin_manager=None,
    ):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self._pwhl = PWHLDataSource(self.logger)
        self._ohl  = OHLDataSource(self.logger)
        self._filter = HockeyGameFilter(self.logger)

        # Per-mode game lists and cycle indices
        self._games:      Dict[str, List[Dict]] = {m: [] for m in _ALL_MODES}
        self._game_idx:   Dict[str, int]        = {m: 0  for m in _ALL_MODES}

        # Download logos for both leagues at startup
        for league in ("pwhl", "ohl"):
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

    def _league_cfg(self, league: str) -> Dict[str, Any]:
        """Merge defaults → league overrides for the given league."""
        defaults = self.config.get("defaults", {})
        overrides = self.config.get(league, {})
        return {**defaults, **overrides}

    # ------------------------------------------------------------------
    # Required plugin interface
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Fetch and cache game data for every mode in one pass."""
        league_cfgs = {lg: self._league_cfg(lg) for lg in ("pwhl", "ohl")}

        recent_days  = {lg: int(league_cfgs[lg].get("recent_days",   2)) for lg in ("pwhl", "ohl")}
        upcoming_days= {lg: int(league_cfgs[lg].get("upcoming_days", 3)) for lg in ("pwhl", "ohl")}

        raw: Dict[str, List[Dict]] = {
            "pwhl_live":     self._pwhl.fetch_live_games(),
            "pwhl_recent":   self._pwhl.fetch_recent_games(recent_days["pwhl"]),
            "pwhl_upcoming": self._pwhl.fetch_upcoming_games(upcoming_days["pwhl"]),
            "ohl_live":      self._ohl.fetch_live_games(),
            "ohl_recent":    self._ohl.fetch_recent_games(recent_days["ohl"]),
            "ohl_upcoming":  self._ohl.fetch_upcoming_games(upcoming_days["ohl"]),
        }

        for mode in _ALL_MODES:
            league = _league_of(mode)
            mode_type = _type_of(mode)
            converted = [_ht_to_renderer(g, league) for g in raw[mode]]
            self._games[mode] = self._filter.filter_and_sort(
                converted, mode_type, league_cfgs[league]
            )
            self._game_idx[mode] = 0
            self.logger.debug(f"{mode}: {len(self._games[mode])} games")

    def display(self, force_clear: bool = False, display_mode: str = "") -> bool:
        """
        Render one game card for the given display_mode.
        LEDMatrix passes the current rotation slot as display_mode.
        Returns False (skip) when there are no games for this mode.
        """
        mode = display_mode or "pwhl_live"
        if mode not in _ALL_MODES:
            self.logger.warning(f"Unknown display_mode: {mode}")
            return False

        games = self._games.get(mode, [])
        if not games:
            return False

        idx = self._game_idx[mode]
        success = self._render(games[idx], _type_of(mode))
        self._game_idx[mode] = (idx + 1) % len(games)
        return success

    def cleanup(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Optional interface — duration & cycle tracking
    # ------------------------------------------------------------------

    def get_display_duration(self) -> float:
        # Use the first league's config as the duration source
        return float(self._league_cfg("pwhl").get("display_duration", 15))

    def is_cycle_complete(self) -> bool:
        """True once all games across all modes have been shown once."""
        return all(idx == 0 for idx in self._game_idx.values())

    # ------------------------------------------------------------------
    # Optional interface — live priority
    # ------------------------------------------------------------------

    def has_live_priority(self) -> bool:
        return (
            bool(self._league_cfg("pwhl").get("live_priority", True)) or
            bool(self._league_cfg("ohl").get("live_priority", True))
        )

    def has_live_content(self) -> bool:
        if not self.has_live_priority():
            return False
        try:
            return (
                len(self._pwhl.fetch_live_games()) > 0 or
                len(self._ohl.fetch_live_games()) > 0
            )
        except Exception:
            return False

    def get_live_modes(self) -> List[str]:
        return ["pwhl_live", "ohl_live"]

    # ------------------------------------------------------------------
    # Optional interface — hot-reload
    # ------------------------------------------------------------------

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        super().on_config_change(new_config)
        self._games    = {m: [] for m in _ALL_MODES}
        self._game_idx = {m: 0  for m in _ALL_MODES}

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
