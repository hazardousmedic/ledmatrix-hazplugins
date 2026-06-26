"""
Game Renderer for Hockey Scoreboard Extended Plugin.

Copied from ChuckBuilds/ledmatrix-plugins hockey-scoreboard and adapted to
support PWHL and OHL logo directories instead of NHL/NCAA paths.

Original: https://github.com/ChuckBuilds/ledmatrix-plugins/blob/main/plugins/hockey-scoreboard/game_renderer.py
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

try:
    RESAMPLE_FILTER = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE_FILTER = Image.LANCZOS


class GameRenderer:
    """Renders individual game cards as PIL Images for display."""

    def __init__(
        self,
        display_width: int,
        display_height: int,
        config: Dict[str, Any],
        logo_cache: Optional[Dict[str, Image.Image]] = None,
        custom_logger: Optional[logging.Logger] = None,
    ):
        self.display_width = display_width
        self.display_height = display_height
        self.config = config
        self.logger = custom_logger or logger
        self._logo_cache = logo_cache if logo_cache is not None else {}
        self.fonts = self._load_fonts()

        # Logo directories — adapted for PWHL and OHL
        self.logo_dirs = {
            "pwhl": config.get("pwhl", {}).get("logo_dir", "assets/sports/pwhl_logos"),
            "ohl": config.get("ohl", {}).get("logo_dir", "assets/sports/ohl_logos"),
        }

        defaults = config.get("defaults", {})
        self.show_records = defaults.get("show_records", config.get("show_records", False))
        self.show_ranking = defaults.get("show_ranking", config.get("show_ranking", False))
        self._team_rankings_cache: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Font loading
    # ------------------------------------------------------------------

    def _load_fonts(self) -> Dict[str, ImageFont.FreeTypeFont]:
        fonts = {}
        customization = self.config.get("customization", {})
        score_config = customization.get("score_text", {})
        period_config = customization.get("period_text", {})
        team_config = customization.get("team_name", {})
        status_config = customization.get("status_text", {})
        detail_config = customization.get("detail_text", {})
        rank_config = customization.get("rank_text", {})

        try:
            fonts["score"] = self._load_custom_font(score_config, default_size=10)
            fonts["time"] = self._load_custom_font(period_config, default_size=8)
            fonts["team"] = self._load_custom_font(team_config, default_size=8)
            fonts["status"] = self._load_custom_font(status_config, default_size=6)
            fonts["detail"] = self._load_custom_font(detail_config, default_size=6)
            fonts["rank"] = self._load_custom_font(rank_config, default_size=10)
        except Exception:
            self.logger.exception("Error loading fonts, falling back to defaults")
            try:
                fonts["score"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
                fonts["time"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["team"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 8)
                fonts["status"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["detail"] = ImageFont.truetype("assets/fonts/4x6-font.ttf", 6)
                fonts["rank"] = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
            except IOError:
                self.logger.warning("Fonts not found, using PIL default font")
                default_font = ImageFont.load_default()
                fonts = {k: default_font for k in ["score", "time", "team", "status", "detail", "rank"]}

        return fonts

    def _load_custom_font(
        self, element_config: Dict[str, Any], default_size: int = 8
    ) -> ImageFont.FreeTypeFont:
        font_name = element_config.get("font", "PressStart2P-Regular.ttf")
        font_size = int(element_config.get("font_size", default_size))
        font_path = os.path.join("assets", "fonts", font_name)

        try:
            if os.path.exists(font_path) and font_path.lower().endswith(".ttf"):
                return ImageFont.truetype(font_path, font_size)
        except Exception as e:
            self.logger.error(f"Error loading font {font_name}: {e}")

        fallback = os.path.join("assets", "fonts", "PressStart2P-Regular.ttf")
        try:
            if os.path.exists(fallback):
                return ImageFont.truetype(fallback, font_size)
        except Exception:
            pass

        return ImageFont.load_default()

    # ------------------------------------------------------------------
    # Logo loading
    # ------------------------------------------------------------------

    def _get_logo_path(self, league: str, team_abbrev: str) -> Path:
        logo_dir = self.logo_dirs.get(league, "assets/sports/pwhl_logos")
        return Path(logo_dir) / f"{team_abbrev}.png"

    def _load_and_resize_logo(
        self,
        team_abbrev: str,
        logo_path: Optional[Path] = None,
        league: str = "pwhl",
    ) -> Optional[Image.Image]:
        cache_key = f"{league}_{team_abbrev}"
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]
        if team_abbrev in self._logo_cache:
            return self._logo_cache[team_abbrev]

        try:
            if logo_path is None or not os.path.exists(logo_path):
                logo_path = self._get_logo_path(league, team_abbrev)

            if logo_path and os.path.exists(logo_path):
                with Image.open(logo_path) as logo_file:
                    logo = logo_file.copy() if logo_file.mode == "RGBA" else logo_file.convert("RGBA")

                bbox = logo.getbbox()
                if bbox:
                    logo = logo.crop(bbox)
                logo.thumbnail((self.display_height, self.display_height), RESAMPLE_FILTER)

                self._logo_cache[cache_key] = logo
                return logo
            else:
                self.logger.debug(f"Logo not found: {logo_path}")
                return None

        except Exception as e:
            self.logger.error(f"Error loading logo for {team_abbrev}: {e}")
            return None

    def preload_logos(self, games: list, logo_dir: Path) -> None:
        for game in games:
            league = game.get("league", "pwhl")
            for team_key in ["home_abbr", "away_abbr"]:
                abbr = game.get(team_key, "")
                cache_key = f"{league}_{abbr}"
                if abbr and cache_key not in self._logo_cache:
                    logo_path_str = game.get(f'{team_key.replace("abbr", "logo_path")}')
                    if logo_path_str:
                        logo_path = (
                            Path(logo_path_str)
                            if os.path.isabs(logo_path_str)
                            else logo_dir / logo_path_str
                        )
                    else:
                        logo_path = logo_dir / f"{abbr}.png"
                    self._load_and_resize_logo(abbr, logo_path, league)
        self.logger.debug(f"Preloaded {len(self._logo_cache)} logos")

    def set_rankings_cache(self, rankings: Dict[str, int]) -> None:
        self._team_rankings_cache = rankings

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_text_with_outline(
        self,
        draw: ImageDraw.Draw,
        text: str,
        position: Tuple[int, int],
        font: ImageFont.FreeTypeFont,
        fill: Tuple[int, int, int] = (255, 255, 255),
        outline_color: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        x, y = position
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    def _normalize_game_payload(self, game: Dict[str, Any]) -> Dict[str, Any]:
        """Accept either flat (home_abbr/away_abbr) or nested (home_team/away_team) dicts."""
        normalized = dict(game)

        has_flat = any(
            k in normalized
            for k in ["home_abbr", "home_score", "away_abbr", "away_score",
                       "home_name", "away_name", "home_record", "away_record"]
        )
        if not has_flat:
            return normalized

        home_team = normalized.get("home_team", {})
        if not isinstance(home_team, dict):
            home_team = {}
        if "home_abbr" in normalized and not home_team.get("abbrev"):
            home_team["abbrev"] = normalized.get("home_abbr", "")
        if "home_score" in normalized and "score" not in home_team:
            home_team["score"] = normalized.get("home_score", "0")
        if "home_name" in normalized and not home_team.get("name"):
            home_team["name"] = normalized.get("home_name", "")
        if "home_record" in normalized and not home_team.get("record"):
            home_team["record"] = normalized.get("home_record", "")
        normalized["home_team"] = home_team

        away_team = normalized.get("away_team", {})
        if not isinstance(away_team, dict):
            away_team = {}
        if "away_abbr" in normalized and not away_team.get("abbrev"):
            away_team["abbrev"] = normalized.get("away_abbr", "")
        if "away_score" in normalized and "score" not in away_team:
            away_team["score"] = normalized.get("away_score", "0")
        if "away_name" in normalized and not away_team.get("name"):
            away_team["name"] = normalized.get("away_name", "")
        if "away_record" in normalized and not away_team.get("record"):
            away_team["record"] = normalized.get("away_record", "")
        normalized["away_team"] = away_team

        status = normalized.get("status", {})
        if not isinstance(status, dict):
            status = {}
        if "status_text" in normalized and not status.get("detail"):
            status["detail"] = normalized.get("status_text", "")
        if "period" in normalized and not status.get("period"):
            status["period"] = normalized.get("period", "")
        if "clock" in normalized and not status.get("clock"):
            status["clock"] = normalized.get("clock", "")
        if "state" in normalized and not status.get("state"):
            status["state"] = normalized.get("state", "")
        normalized["status"] = status

        return normalized

    # ------------------------------------------------------------------
    # Main render entry point
    # ------------------------------------------------------------------

    def render_game_card(
        self,
        game: Dict[str, Any],
        game_type: str = "live",
    ) -> Image.Image:
        """
        Render one game card as a PIL Image.

        Args:
            game:      Normalised game dict from _ht_to_renderer() in manager.py
            game_type: "live", "recent", or "upcoming"

        Returns:
            RGB PIL Image sized (display_width × display_height)
        """
        game = self._normalize_game_payload(game)

        main_img = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 255))
        overlay = Image.new("RGBA", (self.display_width, self.display_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        league = game.get("league", "pwhl")
        logo_dir = Path(self.logo_dirs.get(league, "assets/sports/pwhl_logos"))

        home_team = game.get("home_team", {})
        away_team = game.get("away_team", {})
        home_abbr = home_team.get("abbrev", "")
        away_abbr = away_team.get("abbrev", "")

        home_logo = self._load_and_resize_logo(home_abbr, logo_dir / f"{home_abbr}.png", league)
        away_logo = self._load_and_resize_logo(away_abbr, logo_dir / f"{away_abbr}.png", league)

        if not home_logo or not away_logo:
            return self._render_error_card(f"{away_abbr or '?'}@{home_abbr or '?'}")

        center_y = self.display_height // 2
        logo_slot = min(self.display_height, self.display_width // 2)

        away_x = (logo_slot - away_logo.width) // 2
        away_y = center_y - (away_logo.height // 2)
        main_img.paste(away_logo, (away_x, away_y), away_logo)

        home_slot_start = self.display_width - logo_slot
        home_x = home_slot_start + (logo_slot - home_logo.width) // 2
        home_y = center_y - (home_logo.height // 2)
        main_img.paste(home_logo, (home_x, home_y), home_logo)

        if game_type in ("live", "recent"):
            score_text = f"{away_team.get('score', '0')}-{home_team.get('score', '0')}"
            score_width = draw.textlength(score_text, font=self.fonts["score"])
            score_x = (self.display_width - score_width) // 2
            score_y = (self.display_height // 2) - 3
            self._draw_text_with_outline(draw, score_text, (score_x, score_y), self.fonts["score"])
        else:
            vs_width = draw.textlength("VS", font=self.fonts["score"])
            vs_x = (self.display_width - vs_width) // 2
            vs_y = (self.display_height // 2) - 3
            self._draw_text_with_outline(draw, "VS", (vs_x, vs_y), self.fonts["score"])

        if game_type == "live":
            self._draw_live_status(draw, game)
        elif game_type == "recent":
            self._draw_recent_status(draw)
        elif game_type == "upcoming":
            self._draw_upcoming_status(draw, game)

        if self.show_records or self.show_ranking:
            self._draw_records_or_rankings(draw, game)

        main_img = Image.alpha_composite(main_img, overlay)
        return main_img.convert("RGB")

    def _render_error_card(self, message: str) -> Image.Image:
        img = Image.new("RGB", (self.display_width, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_text_with_outline(draw, message, (5, 5), self.fonts["status"])
        return img

    # ------------------------------------------------------------------
    # Status drawing per game type
    # ------------------------------------------------------------------

    def _draw_live_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        status = game.get("status", {})
        state = status.get("state", "")
        period = status.get("period", "")
        clock = status.get("display_clock", "")

        if state == "in":
            text = f"{period} {clock}".strip()
        elif state == "post":
            text = "Final"
        else:
            text = status.get("short_detail", "")

        w = draw.textlength(text, font=self.fonts["time"])
        self._draw_text_with_outline(
            draw, text, ((self.display_width - w) // 2, 1), self.fonts["time"]
        )

    def _draw_recent_status(self, draw: ImageDraw.Draw) -> None:
        text = "Final"
        w = draw.textlength(text, font=self.fonts["time"])
        self._draw_text_with_outline(
            draw, text, ((self.display_width - w) // 2, 1), self.fonts["time"]
        )

    def _draw_upcoming_status(self, draw: ImageDraw.Draw, game: Dict) -> None:
        status = game.get("status", {})
        text = status.get("short_detail", "")

        if not text:
            start_time = game.get("start_time", "")
            if start_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    text = dt.strftime("%b %d")
                except (ValueError, TypeError):
                    pass

        if text:
            w = draw.textlength(text, font=self.fonts["time"])
            self._draw_text_with_outline(
                draw, text, ((self.display_width - w) // 2, 1), self.fonts["time"]
            )

    def _draw_records_or_rankings(self, draw: ImageDraw.Draw, game: Dict) -> None:
        record_font = self.fonts.get("detail") or ImageFont.load_default()

        home_team = game.get("home_team", {})
        away_team = game.get("away_team", {})

        record_bbox = draw.textbbox((0, 0), "0-0", font=record_font)
        record_height = record_bbox[3] - record_bbox[1]
        record_y = self.display_height - record_height - 4

        away_text = self._get_team_display_text(
            away_team.get("abbrev", ""), away_team.get("record", "")
        )
        if away_text:
            self._draw_text_with_outline(draw, away_text, (3, record_y), record_font)

        home_text = self._get_team_display_text(
            home_team.get("abbrev", ""), home_team.get("record", "")
        )
        if home_text:
            bbox = draw.textbbox((0, 0), home_text, font=record_font)
            home_w = bbox[2] - bbox[0]
            self._draw_text_with_outline(
                draw, home_text, (self.display_width - home_w - 3, record_y), record_font
            )

    def _get_team_display_text(self, abbr: str, record: str) -> str:
        if self.show_ranking:
            rank = self._team_rankings_cache.get(abbr, 0)
            return f"#{rank}" if rank > 0 else ""
        if self.show_records:
            return record
        return ""
