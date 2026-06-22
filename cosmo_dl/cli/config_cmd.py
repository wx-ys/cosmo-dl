"""CLI command: config — manage cosmo-dl settings and authentication."""

from __future__ import annotations

import os

import rich_click as click
from rich.console import Console
from rich.table import Table

from cosmo_dl.config import get, list_keys, set_value, unset

console = Console()


@click.group("config")
def config_cmd() -> None:
    """Manage cosmo-dl configuration and authentication.

    Settings are stored in ~/.config/cosmo-dl/config.toml
    and can also be set via environment variables or .env files.

    \b
    Examples:
      cosmo-dl config set tng_api_key "abc123"
      cosmo-dl config show
      cosmo-dl config get tng_api_key
      cosmo-dl config auth      (show authentication status)
    """
    pass


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value.

    \b
    Common keys:
      tng_api_key     IllustrisTNG API key
      eagle_username  EAGLE database username
      eagle_password  EAGLE database password
    """
    set_value(key, value)
    console.print(f"[green]✓[/green] Set [bold]{key}[/bold].")


@config_cmd.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Get a configuration value (resolved from all sources)."""
    from cosmo_dl.config import _ENV_KEY_MAP, _load_dotenvs, _load_toml

    val = get(key)
    if val:
        console.print(f"[bold]{key}[/bold] = {val}")

        env_var = _ENV_KEY_MAP.get(key, key.upper())
        if os.environ.get(env_var):
            console.print(f"  [dim](source: environment variable {env_var})[/dim]")
        elif env_var in _load_dotenvs():
            console.print("  [dim](source: .env file)[/dim]")
        elif key in _load_toml():
            console.print("  [dim](source: config file ~/.config/cosmo-dl/config.toml)[/dim]")
        else:
            console.print("  [dim](source: default)[/dim]")
    else:
        console.print(f"[dim]{key} is not set.[/dim]")


@config_cmd.command("unset")
@click.argument("key")
def config_unset(key: str) -> None:
    """Remove a configuration key."""
    unset(key)
    console.print(f"[green]✓[/green] Removed [bold]{key}[/bold].")


def _show_auth_status() -> None:
    """Render the authentication status table."""
    from cosmo_dl.config import _ENV_KEY_MAP

    table = Table(title="Authentication Status")
    table.add_column("Key", style="bold")
    table.add_column("Label", style="dim")
    table.add_column("Status")
    table.add_column("Preview", style="dim")

    auth_keys = [
        ("tng_api_key", "TNG API"),
        ("eagle_username", "EAGLE username"),
        ("eagle_password", "EAGLE password"),
    ]

    for key, label in auth_keys:
        token = os.environ.get(_ENV_KEY_MAP.get(key, key.upper()), "") or get(key)
        if token:
            status = "[green]✓ configured[/green]"
            preview = f"{token[:8]}...{token[-4:]}" if len(token) > 16 else "(hidden)"
        else:
            status = "[yellow]✗ not set[/yellow]"
            preview = f"use 'cosmo-dl config set {key} <value>'"
        table.add_row(key, label, status, preview)

    console.print(table)


@config_cmd.command("show")
@click.option("--auth", "auth_only", is_flag=True, help="Show only authentication keys.")
def config_show(auth_only: bool) -> None:
    """Show all configuration values and their sources.

    Use --auth to show only authentication-related keys.
    """
    if auth_only:
        _show_auth_status()
        return

    from cosmo_dl.config import _ENV_KEY_MAP, _load_dotenvs, _load_toml

    dotenv = _load_dotenvs()
    toml_data = _load_toml()

    all_keys = sorted(set(list(_ENV_KEY_MAP.keys()) + list(toml_data.keys())))

    console.print("cosmo-dl configuration\n")
    console.print(f"{'Key':<25s} {'Value':<30s} {'Source':<20s}")
    console.print("-" * 75)

    for key in all_keys:
        val = get(key)
        if not val:
            val = "(not set)"

        env_var = _ENV_KEY_MAP.get(key, key.upper())
        if os.environ.get(env_var):
            source = f"env: {env_var}"
        elif env_var in dotenv:
            source = ".env file"
        elif key in toml_data:
            source = "config.toml"
        else:
            source = "default"

        console.print(f"{key:<25s} {val:<30s} {source:<20s}")


@config_cmd.command("auth")
def config_auth() -> None:
    """Show authentication status for known sources.

    Shortcut for: cosmo-dl config show --auth
    """
    _show_auth_status()


@config_cmd.command("keys")
def config_keys() -> None:
    """List known configuration keys."""
    from cosmo_dl.config import _ENV_KEY_MAP

    console.print("Known configuration keys:")
    for key in list_keys():
        env_var = _ENV_KEY_MAP.get(key, key.upper())
        console.print(f"  {key}  [dim](env: {env_var})[/dim]")
