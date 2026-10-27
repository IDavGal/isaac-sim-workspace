"""Scenario configuration: defaults, a TOML file and command-line overrides."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = WORKSPACE / "config" / "sim.toml"

DEFAULTS: dict[str, dict[str, Any]] = {
    "stage": {"path": "scenes/demo_arm.usda"},
    "run": {
        "mode": "play",
        "duration": 10.0,
        "realtime": False,
        "render_hz": 60.0,
        "settle": 1.0,
    },
    "display": {"mode": "headless", "render": ""},
    "livestream": {
        "signal_port": 49100,
        "stream_port": 47998,
        "public_ip": "",
        "log_level": "error",
    },
    "remote_exec": {"vscode_port": 0},
    "kit": {"experience": "", "extensions": ["isaacsim.ros2.bridge"], "args": []},
    "ros_bridge": {"clock_topic": "/clock", "joints": []},
    "checks": {
        "articulations": [],
        "max_log_errors": -1,
        "min_topic_rate": 0.8,
        "topics": [],
    },
    "output": {"summary": "", "log_file": ""},
}

CHOICES = {
    ("run", "mode"): {"play", "interactive"},
    ("display", "mode"): {"headless", "window", "livestream"},
    ("display", "render"): {"", "none", "minimal", "rtx"},
    ("livestream", "log_level"): {"silence", "error", "warning", "info", "debug", "verbose"},
}


# Keys of each entry in the array-of-tables settings.
TABLE_KEYS = {
    "ros_bridge.joints": {"articulation", "state_topic", "command_topic"},
    "checks.topics": {"name", "type"},
}


class ConfigError(ValueError):
    """The configuration names an unknown key or holds an invalid value."""


def _parse_value(text: str) -> Any:
    """A TOML value, or the text itself when it is not valid TOML (bare strings)."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


def _merge(base: dict, override: dict, where: str = "") -> None:
    for key, value in override.items():
        path = f"{where}.{key}" if where else key
        if key not in base:
            raise ConfigError(f"unknown key: {path}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{path} must be a table")
            _merge(base[key], value, path)
        else:
            base[key] = value


def _validate_tables(cfg: dict) -> None:
    for where, entries, keys in [
        ("ros_bridge.joints", cfg["ros_bridge"]["joints"], TABLE_KEYS["ros_bridge.joints"]),
        ("checks.topics", cfg["checks"]["topics"], TABLE_KEYS["checks.topics"]),
    ]:
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or set(entry) != keys:
                raise ConfigError(f"{where}[{i}] must have exactly the keys {sorted(keys)}")


def _validate(cfg: dict) -> None:
    _validate_tables(cfg)
    for (section, key), allowed in CHOICES.items():
        if cfg[section][key] not in allowed:
            raise ConfigError(f"{section}.{key} must be one of {sorted(allowed)}")
    for section, values in DEFAULTS.items():
        for key, default in values.items():
            value = cfg[section][key]
            # Integers are valid where floats are expected.
            ok = isinstance(value, type(default)) or (
                isinstance(default, float) and isinstance(value, int)
            )
            if not ok or (type(default) is int and isinstance(value, bool)):
                raise ConfigError(f"{section}.{key} must be a {type(default).__name__}")


def load(path: Path | None = None, overrides: list[str] | None = None) -> dict:
    """Defaults, merged with the TOML file, then with `section.key=value` overrides."""
    cfg = copy.deepcopy(DEFAULTS)
    path = path or DEFAULT_CONFIG
    with open(path, "rb") as f:
        _merge(cfg, tomllib.load(f))
    for item in overrides or []:
        dotted, sep, text = item.partition("=")
        section, dot, key = dotted.partition(".")
        if not sep or not dot:
            raise ConfigError(f"expected section.key=value, got {item!r}")
        _merge(cfg, {section: {key: _parse_value(text)}})
    _validate(cfg)
    return cfg


def resolve(path: str) -> Path:
    """A configured path, relative to the workspace root unless absolute."""
    p = Path(path)
    return p if p.is_absolute() else WORKSPACE / p
