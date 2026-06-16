"""Tests for CLI."""
from click.testing import CliRunner
from cosmo_dl.cli.main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "download" in result.output
    assert "explore" in result.output
    assert "source" in result.output
    assert "config" in result.output


def test_config_set_and_get():
    """Test config set and get commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set", "test_key", "test_val"])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["config", "get", "test_key"])
    assert result.exit_code == 0
    assert "test_val" in result.output
    runner.invoke(cli, ["config", "unset", "test_key"])


def test_config_show():
    """Test config show command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "show"])
    assert result.exit_code == 0
    assert "tng_api_key" in result.output


def test_config_keys():
    """Test config keys command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "keys"])
    assert result.exit_code == 0
    assert "tng_api_key" in result.output


def test_explore_command_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["explore", "--help"])
    assert result.exit_code == 0
    assert "--recursive" in result.output
    assert "--include" in result.output


def test_source_list_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["source", "list"])
    assert result.exit_code == 0
    assert "FIRE" in result.output
    assert "Auriga" in result.output


def test_source_info_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["source", "info", "FIRE"])
    assert result.exit_code == 0
    assert "FIRE" in result.output


def test_download_command_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["download", "--help"])
    assert result.exit_code == 0
    assert "--workers" in result.output
    assert "--limit" in result.output
