"""Tests for the config module."""

import os
import tempfile
from pathlib import Path

import pytest

from cosmo_dl import config


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch, tmp_path):
    """Ensure a clean config state before each test by redirecting all
    config file paths to temporary directories."""
    # Redirect TOML config to temp
    temp_config = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_FILE", temp_config)
    # Redirect .env files to temp (avoid the project's real .env)
    temp_dotenv = tmp_path / ".env"
    monkeypatch.setattr(config, "LOCAL_ENV_FILE", temp_dotenv)
    monkeypatch.setattr(config, "GLOBAL_ENV_FILE", temp_dotenv)
    # Clean env vars
    for env_var in ["TNG_API_KEY", "COSMO_DL_OFFLINE"]:
        os.environ.pop(env_var, None)
    yield
    os.environ.pop("TNG_API_KEY", None)


class TestDotenvParsing:
    def test_parse_simple(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY1=value1\nKEY2=value2\n")
            f.flush()
            result = config._parse_dotenv(Path(f.name))
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_parse_with_comments_and_blanks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# comment\n\nKEY=val\n  # another comment\n")
            f.flush()
            result = config._parse_dotenv(Path(f.name))
        assert result == {"KEY": "val"}

    def test_parse_quoted_values(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY=\"quoted value\"\nKEY2='single quoted'\n")
            f.flush()
            result = config._parse_dotenv(Path(f.name))
        assert result == {"KEY": "quoted value", "KEY2": "single quoted"}

    def test_parse_missing_file(self):
        result = config._parse_dotenv(Path("/nonexistent/.env"))
        assert result == {}


class TestConfigGet:
    def test_env_var_priority(self, monkeypatch):
        """Environment variable has the highest priority."""
        monkeypatch.setenv("TNG_API_KEY", "env-key")
        # Also set in toml config
        config.set_value("tng_api_key", "toml-key")
        try:
            result = config.get("tng_api_key")
            assert result == "env-key"
        finally:
            config.unset("tng_api_key")

    def test_fallback_to_toml(self, monkeypatch):
        """When env var is not set, fall back to TOML config."""
        monkeypatch.delenv("TNG_API_KEY", raising=False)
        config.set_value("tng_api_key", "toml-key")
        try:
            result = config.get("tng_api_key")
            assert result == "toml-key"
        finally:
            config.unset("tng_api_key")

    def test_default_value(self, monkeypatch):
        """Return default when no source has the key."""
        monkeypatch.delenv("TNG_API_KEY", raising=False)
        config.unset("tng_api_key")
        result = config.get("tng_api_key", "my-default")
        assert result == "my-default"

    def test_get_empty_string_is_falsy(self, monkeypatch):
        """Empty env var is treated as not set."""
        monkeypatch.setenv("TNG_API_KEY", "")
        config.set_value("tng_api_key", "toml-key")
        try:
            result = config.get("tng_api_key")
            # Empty env var → should skip and use toml
            assert result == "toml-key"
        finally:
            config.unset("tng_api_key")


class TestConfigSetUnset:
    def test_set_and_get(self):
        config.set_value("test_key", "test_val")
        try:
            result = config.get("test_key")
            assert result == "test_val"
        finally:
            config.unset("test_key")

    def test_unset_removes_key(self):
        config.set_value("test_key", "test_val")
        config.unset("test_key")
        result = config.get("test_key", "default")
        assert result == "default"

    def test_show_includes_all(self):
        config.set_value("tng_api_key", "show-key")
        try:
            result = config.show()
            assert "tng_api_key" in result
            assert result["tng_api_key"] == "show-key"
        finally:
            config.unset("tng_api_key")


class TestListKeys:
    def test_list_keys_returns_known_keys(self):
        keys = config.list_keys()
        assert "tng_api_key" in keys
