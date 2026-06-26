#!/usr/bin/env python3
"""
Syncs manifest.json files from each plugin directory into plugins.json.
Run this after bumping a plugin version.

Usage:
    python update_registry.py
    python update_registry.py --dry-run
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:
    import semver
except ImportError:
    print("Missing dependency: pip install semver", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent
PLUGINS_DIR = ROOT / "plugins"
REGISTRY_FILE = ROOT / "plugins.json"

SYNCED_FIELDS = ["name", "description", "author", "category", "tags", "icon"]


def read_manifest(plugin_dir: Path) -> dict | None:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with manifest_path.open() as f:
        return json.load(f)


def is_newer(new_ver: str, old_ver: str) -> bool:
    try:
        return semver.Version.parse(new_ver) > semver.Version.parse(old_ver)
    except ValueError:
        return False


def main(dry_run: bool = False) -> None:
    with REGISTRY_FILE.open() as f:
        registry = json.load(f)

    changed = []

    for entry in registry["plugins"]:
        plugin_path = entry.get("plugin_path")
        if not plugin_path:
            continue

        plugin_dir = ROOT / plugin_path
        manifest = read_manifest(plugin_dir)
        if not manifest:
            print(f"  WARNING: no manifest.json found at {plugin_dir}")
            continue

        manifest_version = manifest.get("version", "")
        registry_version = entry.get("latest_version", "0.0.0")

        if is_newer(manifest_version, registry_version):
            print(f"  Updating {entry['id']}: {registry_version} -> {manifest_version}")
            entry["latest_version"] = manifest_version
            entry["last_updated"] = manifest.get("last_updated", str(date.today()))
            for field in SYNCED_FIELDS:
                if field in manifest:
                    entry[field] = manifest[field]
            changed.append(entry["id"])
        else:
            print(f"  {entry['id']} is up to date ({registry_version})")

    if dry_run:
        print("\nDry run — no changes written.")
        return

    if changed:
        registry["last_updated"] = str(date.today())
        with REGISTRY_FILE.open("w", newline="\n") as f:
            json.dump(registry, f, indent=2)
            f.write("\n")
        print(f"\nUpdated registry for: {', '.join(changed)}")
    else:
        print("\nRegistry already up to date.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
