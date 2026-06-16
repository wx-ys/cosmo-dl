"""Global configuration management.

Reads settings from multiple sources with this priority (highest first):

1. Environment variables (``export COSMO_TNG_API_KEY=...``)
2. ``.env`` files (``./.env`` and ``~/.config/cosmo-dl/.env``)
3. Config file (``~/.config/cosmo-dl/config.toml``)
4. Built-in defaults
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".config" / "cosmo-dl"
CONFIG_FILE = CONFIG_DIR / "config.toml"
GLOBAL_ENV_FILE = CONFIG_DIR / ".env"
LOCAL_ENV_FILE = Path.cwd() / ".env"

# Mapping of config keys to environment variable names
_ENV_KEY_MAP: dict[str, str] = {
    "tng_api_key": "TNG_API_KEY",
    "fire_api_key": "FIRE_API_KEY",
}


# ---------------------------------------------------------------------------
# .env file loading
# ---------------------------------------------------------------------------

def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict, skipping comments and blank lines."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
    return result


def _load_dotenvs() -> dict[str, str]:
    """Load env vars from all .env files (local overrides global)."""
    merged: dict[str, str] = {}

    # Global .env
    for k, v in _parse_dotenv(GLOBAL_ENV_FILE).items():
        merged[k] = v

    # Local .env (overrides global)
    for k, v in _parse_dotenv(LOCAL_ENV_FILE).items():
        merged[k] = v

    return merged


# ---------------------------------------------------------------------------
# TOML config file
# ---------------------------------------------------------------------------

def _load_toml() -> dict[str, object]:
    """Load the TOML config file, returning empty dict if not found."""
    if not CONFIG_FILE.is_file():
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)  # type: ignore[no-any-return]


def _save_toml(data: dict[str, object]) -> None:
    """Save the TOML config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Simple TOML writer — sufficient for flat key-value pairs
    lines: list[str] = []
    for key, value in sorted(data.items()):
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
    with open(CONFIG_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(key: str, default: str = "") -> str:
    """Get a configuration value.

    Resolution order:
    1. Environment variable (mapped via ``_ENV_KEY_MAP``)
    2. ``.env`` files (local overrides global)
    3. TOML config file
    4. *default*

    Parameters
    ----------
    key : str
        Config key name (e.g. ``"tng_api_key"``).
    default : str
        Value returned when the key is not found anywhere.
    """
    # 1. Environment variable
    env_var = _ENV_KEY_MAP.get(key, key.upper())
    env_val = os.environ.get(env_var)
    if env_val is not None and env_val != "":
        return env_val

    # 2. .env files
    dotenv = _load_dotenvs()
    if env_var in dotenv and dotenv[env_var]:
        return dotenv[env_var]

    # 3. TOML config
    toml_data = _load_toml()
    if key in toml_data:
        val = toml_data[key]
        if isinstance(val, str):
            return val

    # 4. Default
    return default


def set_value(key: str, value: str) -> None:
    """Persist a configuration key-value pair to the TOML config file.

    Parameters
    ----------
    key : str
        Config key name.
    value : str
        Value to store.
    """
    data = _load_toml()
    data[key] = value  # type: ignore[assignment]
    _save_toml(data)  # type: ignore[arg-type]


def unset(key: str) -> None:
    """Remove a configuration key from the TOML config file."""
    data = _load_toml()
    if key in data:
        del data[key]
        _save_toml(data)  # type: ignore[arg-type]


def show() -> dict[str, str]:
    """Return all resolved configuration values (including env sources)."""
    result: dict[str, str] = {}

    # Collect from all sources
    toml_data = _load_toml()
    dotenv = _load_dotenvs()

    all_keys: set[str] = set()
    all_keys.update(_ENV_KEY_MAP.keys())
    all_keys.update(toml_data.keys())

    for key in sorted(all_keys):
        result[key] = get(key)

    return result


def list_keys() -> list[str]:
    """Return known config key names."""
    return sorted(_ENV_KEY_MAP.keys())
