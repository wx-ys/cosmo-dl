"""CLI command: source."""
import click
from cosmo_dl.api import list_sources as api_list_sources
from cosmo_dl.registry.registry import Registry

@click.group("source")
def source_cmd():
    """Manage simulation data sources."""
    pass

@source_cmd.command("list")
def source_list():
    """List all known sources."""
    names = api_list_sources()
    reg = Registry()
    for name in names:
        src = reg.get(name)
        if src:
            click.echo(f"  {name:20s}  {src.description}")

@source_cmd.command("info")
@click.argument("name")
def source_info(name):
    """Show source details."""
    reg = Registry()
    src = reg.get(name)
    if src is None:
        click.echo(f"Unknown source: {name!r}")
        raise SystemExit(1)
    click.echo(f"Name:        {src.name}")
    click.echo(f"Description: {src.description}")
    click.echo(f"Base URL:    {src.base_url}")
    click.echo(f"Structure:   {src.structure}")
    click.echo(f"Auth:        {src.auth.type if src.auth else 'none'}")
    click.echo(f"Datasets:    {len(src.datasets)}")
    for ds_name, ds in src.datasets.items():
        chunks_info = f" ({ds.chunks} chunks)" if ds.chunks else ""
        click.echo(f"  - {ds_name}: {ds.path}{chunks_info}")
