"""CLI entry point for cosmo-dl."""
import rich_click as click

from cosmo_dl.cli.auth_cmd import auth_cmd
from cosmo_dl.cli.config_cmd import config_cmd
from cosmo_dl.cli.download_cmd import download_cmd
from cosmo_dl.cli.explore_cmd import explore_cmd
from cosmo_dl.cli.source_cmd import source_cmd


@click.group()
@click.version_option(version="0.1.0", prog_name="cosmo-dl")
def cli() -> None:
    """cosmo-dl — Download cosmological simulation data."""
    pass

cli.add_command(auth_cmd)
cli.add_command(config_cmd)
cli.add_command(download_cmd)
cli.add_command(explore_cmd)
cli.add_command(source_cmd)
