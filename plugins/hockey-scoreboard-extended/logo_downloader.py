"""
Logo downloader for hockey-scoreboard-extended.

Fetches team logos from the HockeyTech leaguestat CDN, which provides logo
URLs directly in the scorebar API response (HomeLogo / VisitorLogo fields).
Falls back to a text-based placeholder for any team whose URL is missing or
whose download fails.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "LEDMatrix/1.0",
    "Accept": "image/png,image/*,*/*",
}

_HOCKEYTECH_BASE = "https://lscluster.hockeytech.com/feed/"

# HockeyTech credentials per league
_LEAGUE_CREDS = {
    "pwhl": {"key": "446521baf8c38984", "client_code": "pwhl"},
    "ohl":  {"key": "f1aa699db3d81487", "client_code": "ohl"},
}

# Logo output directories relative to the LEDMatrix working directory
_LOGO_DIRS = {
    "pwhl": Path("assets/sports/pwhl_logos"),
    "ohl":  Path("assets/sports/ohl_logos"),
}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _fetch_team_logos(league: str, session: requests.Session) -> Dict[str, str]:
    """
    Query HockeyTech scorebar with a wide date window to collect every team
    code + logo URL the API knows about. Returns {abbrev: logo_url}.
    """
    creds = _LEAGUE_CREDS[league]
    params = {
        "feed": "modulekit",
        "view": "scorebar",
        "key": creds["key"],
        "client_code": creds["client_code"],
        "site_id": "0",
        "league_id": "0",
        "lang": "en",
        "numberofdaysback": "180",
        "numberofdaysahead": "180",
    }
    try:
        resp = session.get(_HOCKEYTECH_BASE, headers={"User-Agent": "LEDMatrix/1.0",
                                                       "Accept": "application/json"},
                           params=params, timeout=15)
        resp.raise_for_status()
        games = resp.json().get("SiteKit", {}).get("Scorebar", [])
    except Exception as e:
        logger.error(f"{league.upper()} logo fetch failed: {e}")
        return {}

    teams: Dict[str, str] = {}
    for game in games:
        for code_key, url_key in [("HomeCode", "HomeLogo"), ("VisitorCode", "VisitorLogo")]:
            code = str(game.get(code_key, "")).strip()
            url  = str(game.get(url_key,  "")).strip()
            if code and code not in teams:
                teams[code] = url  # may be empty string — handled below

    return teams


def _download_logo(url: str, dest: Path, session: requests.Session) -> bool:
    """Download a single logo PNG. Returns True on success."""
    try:
        resp = session.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        logger.debug(f"Downloaded logo → {dest}")
        return True
    except Exception as e:
        logger.warning(f"Logo download failed ({url}): {e}")
        return False


def _create_placeholder(abbrev: str, dest: Path) -> None:
    """Write a 64×64 transparent PNG with the team abbreviation as text."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("assets/fonts/PressStart2P-Regular.ttf", 10)
    except Exception:
        font = ImageFont.load_default()

    text = abbrev[:4]
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (64 - (bbox[2] - bbox[0])) // 2
    y = (64 - (bbox[3] - bbox[1])) // 2

    for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    img.save(dest)
    logger.debug(f"Created placeholder logo → {dest}")


def ensure_logos(league: str, force: bool = False) -> None:
    """
    Download missing logos for every team in the given league.

    Args:
        league: "pwhl" or "ohl"
        force:  Re-download even if the file already exists
    """
    if league not in _LEAGUE_CREDS:
        logger.error(f"Unknown league for logo download: {league}")
        return

    logo_dir = _LOGO_DIRS[league]
    session = _make_session()

    logger.info(f"Checking {league.upper()} logos in {logo_dir} ...")
    teams = _fetch_team_logos(league, session)

    if not teams:
        logger.warning(f"No {league.upper()} teams found — skipping logo download")
        return

    downloaded = skipped = placeholder = 0

    for abbrev, url in teams.items():
        dest = logo_dir / f"{abbrev}.png"

        if dest.exists() and not force:
            skipped += 1
            continue

        if url:
            ok = _download_logo(url, dest, session)
            if ok:
                downloaded += 1
                continue

        # No URL or download failed → placeholder
        _create_placeholder(abbrev, dest)
        placeholder += 1

    logger.info(
        f"{league.upper()} logos: {downloaded} downloaded, "
        f"{skipped} already present, {placeholder} placeholders created"
    )


def ensure_all_logos(force: bool = False) -> None:
    """Download missing logos for all supported leagues."""
    for league in _LEAGUE_CREDS:
        ensure_logos(league, force=force)
