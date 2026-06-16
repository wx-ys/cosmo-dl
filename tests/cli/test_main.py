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
