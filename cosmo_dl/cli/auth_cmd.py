"""CLI command: auth — manage authentication tokens for data sources."""
from __future__ import annotations

import os

import rich_click as click
from rich.console import Console
from rich.table import Table

from cosmo_dl.config import get as config_get
from cosmo_dl.config import set_value, unset

console = Console()


@click.group("auth")
def auth_cmd() -> None:
    """Manage authentication for simulation data sources.

    \b
    Examples:
      cosmo-dl auth status
      cosmo-dl auth set  <key> <token>
      cosmo-dl auth unset <key>
    """
    pass


@auth_cmd.command("set")
@click.argument("key")
@click.argument("token")
def auth_set(key: str, token: str) -> None:
    """Store an authentication token.

    KEY is the config key (e.g. 'tng_api_key', 'globus_token').
    TOKEN is the token value.
    """
    set_value(key, token)
    console.print(f"[green]✓[/green] Stored [bold]{key}[/bold].")


@auth_cmd.command("unset")
@click.argument("key")
def auth_unset(key: str) -> None:
    """Remove a stored authentication token."""
    unset(key)
    console.print(f"[green]✓[/green] Removed [bold]{key}[/bold].")


@auth_cmd.command("status")
def auth_status() -> None:
    """Show authentication status for known sources."""
    table = Table(title="Authentication Status")
    table.add_column("Key", style="bold")
    table.add_column("Label", style="dim")
    table.add_column("Status")
    table.add_column("Preview", style="dim")

    keys = [
        ("tng_api_key", "TNG API"),
        ("eagle_username", "EAGLE username"),
        ("eagle_password", "EAGLE password"),
        ("globus_token", "Globus (Auriga)"),
    ]

    for key, label in keys:
        token = os.environ.get(f"COSMO_{key.upper()}", "") or config_get(key)
        if token:
            status = "[green]✓ configured[/green]"
            preview = f"{token[:8]}...{token[-4:]}" if len(token) > 16 else "(hidden)"
        else:
            status = "[yellow]✗ not set[/yellow]"
            preview = f"use 'cosmo-dl auth set {key} <token>'"
        table.add_row(key, label, status, preview)

    console.print(table)
