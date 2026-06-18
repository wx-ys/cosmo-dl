"""CLI command: auth — manage authentication tokens for data sources."""
from __future__ import annotations

import click

from cosmo_dl.config import get as config_get, set_value, unset


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
    click.echo(f"✓ Stored {key}.")


@auth_cmd.command("unset")
@click.argument("key")
def auth_unset(key: str) -> None:
    """Remove a stored authentication token."""
    unset(key)
    click.echo(f"✓ Removed {key}.")


@auth_cmd.command("status")
def auth_status() -> None:
    """Show authentication status for known sources."""
    import os

    click.echo(f"{'Key':<25s} {'Status':<20s} {'Preview':<30s}")
    click.echo("-" * 75)

    keys = [
        ("tng_api_key", "TNG API"),
        ("eagle_username", "EAGLE username"),
        ("eagle_password", "EAGLE password"),
        ("globus_token", "Globus (Auriga)"),
    ]

    for key, label in keys:
        token = os.environ.get(f"COSMO_{key.upper()}", "") or config_get(key)
        if token:
            status = click.style("✓ configured", fg="green")
            preview = f"{token[:8]}...{token[-4:]}" if len(token) > 16 else "(hidden)"
        else:
            status = click.style("✗ not set", fg="yellow")
            preview = f"use 'cosmo-dl auth set {key} <token>'"
        click.echo(f"{key:<25s} {status:<20s} {preview:<30s}")
