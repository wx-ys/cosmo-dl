"""CLI command: source — manage simulation data sources."""
import click
from cosmo_dl.api import list_sources as api_list_sources
from cosmo_dl.registry.registry import Registry


@click.group("source")
def source_cmd() -> None:
    """Manage simulation data sources."""
    pass


@source_cmd.command("list")
@click.option("--flat", is_flag=True, default=False,
              help="Display sources as a flat list (default: grouped)")
def source_list(flat: bool) -> None:
    """List all known simulation sources, grouped by project."""
    reg = Registry()

    if not flat:
        groups = reg.list_by_group()
        for group_name, names in groups.items():
            click.echo(f"\n[{group_name}]")
            for name in names:
                src = reg.get(name)
                desc = src.description if src else ""
                click.echo(f"  {name:<25s}  {desc}")
    else:
        for name in reg.list():
            src = reg.get(name)
            if src:
                click.echo(f"  {name:<25s}  {src.description}")


@source_cmd.command("info")
@click.argument("name")
def source_info(name: str) -> None:
    """Show details about a simulation source."""
    reg = Registry()
    src = reg.get(name)
    if src is None:
        click.echo(f"Unknown source: {name!r}")
        raise SystemExit(1)

    click.echo(f"Name:        {src.name}")
    click.echo(f"Group:       {src.group or '(none)'}")
    click.echo(f"Description: {src.description}")
    click.echo(f"Base URL:    {src.base_url}")
    click.echo(f"Structure:   {src.structure}")
    click.echo(f"Auth:        {src.auth.type if src.auth else 'none'}")
    click.echo(f"Datasets:    {len(src.datasets)}")

    # Show first 20 datasets, then summarize
    items = sorted(src.datasets.items())
    for ds_name, ds in items[:20]:
        chunks_info = f" ({ds.chunks} chunks)" if ds.chunks else ""
        click.echo(f"  - {ds_name}: {ds.path}{chunks_info}")
    if len(items) > 20:
        click.echo(f"  ... and {len(items) - 20} more datasets")


@source_cmd.command("discover")
@click.argument("group", default="TNG")
@click.option("--include", default="*",
              help="Glob pattern to filter simulation names")
@click.option("--exclude", default=None,
              help="Glob pattern to exclude simulation names")
def source_discover(group: str, include: str, exclude: str | None) -> None:
    """Auto-discover simulations from a source group's API.

    Currently supports: TNG (IllustrisTNG project API).

    Examples:

        cosmo-dl source discover TNG

        cosmo-dl source discover TNG --include "TNG100*"

        cosmo-dl source discover TNG --exclude "*-Dark"
    """
    if group.upper() != "TNG":
        click.echo(f"Discovery not yet supported for group {group!r}. "
                   f"Currently supported: TNG")
        raise SystemExit(1)

    from cosmo_dl.registry.builtin.tng import discover_tng_simulations

    click.echo(f"Querying TNG API for available simulations...")

    sims = discover_tng_simulations(include=include, exclude=exclude)

    if not sims:
        click.echo("No simulations found.")
        return

    click.echo(f"\nFound {len(sims)} simulation(s):\n")
    for name, desc in sims:
        click.echo(f"  {name:<25s}  {desc}")

    # Ask if user wants to refresh the registry
    click.echo(
        f"\nRun 'cosmo-dl source list' to see all available sources.\n"
        f"Use 'cosmo-dl download {sims[0][0]}/groupcat-0' to download data."
    )
