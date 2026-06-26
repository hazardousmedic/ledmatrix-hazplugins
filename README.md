# ledmatrix-hazplugins

Personal LEDMatrix plugin repository. Covers leagues and features not included in the official [ledmatrix-plugins](https://github.com/ChuckBuilds/ledmatrix-plugins) repo.

## Installing a plugin

```bash
curl -X POST http://<pi-ip>:5000/api/plugins/install-from-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/your-username/ledmatrix-hazplugins", "plugin_id": "hockey-scoreboard-extended"}'
```

## Plugins

| Plugin | Leagues | Status |
|--------|---------|--------|
| [hockey-scoreboard-extended](plugins/hockey-scoreboard-extended/) | PWHL, OHL | Active |

## Adding a new plugin

1. Create `plugins/<your-plugin-id>/` with at minimum `manifest.json` and `manager.py`.
2. Copy the structure from an existing plugin.
3. Run `python update_registry.py` to sync the version into `plugins.json`.
4. Commit and push.

## Registry maintenance

```bash
# Preview changes without writing
python update_registry.py --dry-run

# Apply changes
python update_registry.py
```
