"""CLI command: explore."""
import click
from cosmo_dl.api import explore as api_explore

@click.command("explore")
@click.argument("url")
@click.option("--recursive/--no-recursive", default=True)
@click.option("--depth", type=int, default=None)
@click.option("--include", default="*")
@click.option("--exclude", default=None)
def explore_cmd(url, recursive, depth, include, exclude):
    """List files available at a URL."""
    click.echo(f"Exploring {url} ...")
    files = api_explore(url, recursive=recursive, max_depth=depth,
                        include=include, exclude=exclude)
    if not files:
        click.echo("No files found.")
        return
    total_size = sum(f.size for f in files if f.size)
    click.echo(f"\nFound {len(files)} file(s):")
    for f in files:
        size_str = _format_size(f.size) if f.size else "?"
        click.echo(f"  {size_str:>10s}  {f.name}")
    if total_size > 0:
        click.echo(f"\nTotal: {_format_size(total_size)}")

def _format_size(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
