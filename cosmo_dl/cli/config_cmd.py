"""CLI command: config — manage cosmo-dl settings."""
from __future__ import annotations

import click
from cosmo_dl.config import get, set_value, unset, show, list_keys


@click.group("config")
def config_cmd() -> None:
    """Manage cosmo-dl configuration.

    Settings are stored in ~/.config/cosmo-dl/config.toml
    and can also be set via environment variables or .env files.

    \b
    Examples:
      cosmo-dl config set tng_api_key "abc123"
      cosmo-dl config show
      cosmo-dl config get tng_api_key
    """
    pass


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value.

    \b
    Common keys:
      tng_api_key    IllustrisTNG API key
    """
    set_value(key, value)
    click.echo(f"Set {key} = {value}")


@config_cmd.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Get a configuration value (resolved from all sources)."""
    val = get(key)
    if val:
        click.echo(f"{key} = {val}")
        # Indicate the source
        import os
        from cosmo_dl.config import _ENV_KEY_MAP, _load_dotenvs, _load_toml
        env_var = _ENV_KEY_MAP.get(key, key.upper())
        if os.environ.get(env_var):
            click.echo(f"  (source: environment variable {env_var})")
        elif env_var in _load_dotenvs():
            click.echo(f"  (source: .env file)")
        elif key in _load_toml():
            click.echo(f"  (source: config file ~/.config/cosmo-dl/config.toml)")
        else:
            click.echo(f"  (source: default)")
    else:
        click.echo(f"{key} is not set.")


@config_cmd.command("unset")
@click.argument("key")
def config_unset(key: str) -> None:
    """Remove a configuration key."""
    unset(key)
    click.echo(f"Removed {key} from config file.")


@config_cmd.command("show")
def config_show() -> None:
    """Show all configuration values and their sources."""
    import os
    from cosmo_dl.config import _ENV_KEY_MAP, _load_dotenvs, _load_toml

    dotenv = _load_dotenvs()
    toml_data = _load_toml()

    click.echo("cosmo-dl configuration\n")
    click.echo(f"{'Key':<25s} {'Value':<30s} {'Source':<20s}")
    click.echo("-" * 75)

    all_keys = sorted(set(
        list(_ENV_KEY_MAP.keys()) + list(toml_data.keys())
    ))

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

        click.echo(f"{key:<25s} {val:<30s} {source:<20s}")


@config_cmd.command("keys")
def config_keys() -> None:
    """List known configuration keys."""
    from cosmo_dl.config import _ENV_KEY_MAP
    click.echo("Known configuration keys:")
    for key in list_keys():
        env_var = _ENV_KEY_MAP.get(key, key.upper())
        click.echo(f"  {key}  (env: {env_var})")
