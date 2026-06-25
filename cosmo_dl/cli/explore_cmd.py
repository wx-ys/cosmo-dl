"""CLI command: explore."""

import rich_click as click
from rich.console import Console

from cosmo_dl.api import explore as api_explore
from cosmo_dl.progress import fmt_bytes

console = Console()


@click.command("explore")
@click.argument("url")
@click.option(
    "--recursive/--no-recursive",
    default=True,
    help="Recursively explore sub-directories (default: enabled).",
)
@click.option(
    "--depth",
    type=int,
    default=None,
    help="Maximum depth for recursive exploration (default: unlimited).",
)
@click.option("--include", default="*", help="Pattern to include files (default: '*').")
@click.option("--exclude", default=None, help="Pattern to exclude files (default: none).")
def explore_cmd(url, recursive, depth, include, exclude):
    """List files available at a URL."""
    with console.status(
        f"[bold blue]Scanning {url.rstrip('/').rsplit('/', 1)[-1] or url}...[/bold blue]"
    ) as status:

        def _on_progress(files_found: int, total_bytes: int, scanning_url: str) -> None:
            if scanning_url:
                short = scanning_url.rstrip("/").rsplit("/", 1)[-1] or scanning_url
                status.update(
                    f"[bold blue]Scanning {short}/[/bold blue] "
                    f"([green]{files_found}[/green] files so far)"
                )
            else:
                size_str = fmt_bytes(total_bytes) if total_bytes else "..."
                status.update(
                    f"[bold blue]Exploring...[/bold blue] "
                    f"[green]{files_found}[/green] files "
                    f"([dim]{size_str}[/dim])"
                )

        files = api_explore(
            url,
            recursive=recursive,
            max_depth=depth,
            include=include,
            exclude=exclude,
            on_progress=_on_progress,
        )
    if not files:
        console.print("No files found.")
        return
    total_size = sum(f.size for f in files if f.size)
    console.print(f"\nFound [green]{len(files)}[/green] file(s):")
    for f in files:
        size_str = _format_size(f.size) if f.size else "?"
        console.print(f"  {size_str:>10s}  {f.name}")
    if total_size > 0:
        console.print(f"\nTotal: {_format_size(total_size)}")


def _format_size(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
