"""Load swe_config.json for review and gate configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "review": {
        "enabled": True,
        "model": "anthropic:claude-sonnet-4-6",
        "max_retries": 3,
    },
    "gates": {
        "enabled": True,
        "commands": [],
    },
}

_CONFIG_FILENAME = "swe_config.json"


def load_swe_config(search_path: Path | None = None) -> dict[str, Any]:
    """Load swe_config.json, walking up from search_path to find it.

    Falls back to defaults for any missing keys.

    Args:
        search_path: Directory to start searching from. Defaults to cwd.

    Returns:
        Merged config dict with defaults applied.
    """
    start = search_path or Path.cwd()
    config_file = _find_config(start)

    if config_file is None:
        logger.debug("No %s found from %s, using defaults", _CONFIG_FILENAME, start)
        return _deep_merge({}, _DEFAULTS)

    try:
        raw = json.loads(config_file.read_text())
        logger.debug("Loaded %s from %s", _CONFIG_FILENAME, config_file)
        return _deep_merge(raw, _DEFAULTS)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s — using defaults", config_file, exc)
        return _deep_merge({}, _DEFAULTS)


def _find_config(start: Path) -> Path | None:
    """Walk up directory tree looking for swe_config.json."""
    current = start.resolve()
    for _ in range(6):  # don't walk past the filesystem root
        candidate = current / _CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _deep_merge(user: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Return defaults merged with user values (user wins on conflicts)."""
    result = dict(defaults)
    for key, value in user.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(value, result[key])
        else:
            result[key] = value
    return result
