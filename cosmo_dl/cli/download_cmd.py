"""CLI command: download."""

from __future__ import annotations

import os
import signal

import rich_click as click
from rich.console import Console

from cosmo_dl.api import download as api_download
from cosmo_dl.api import explore as api_explore
from cosmo_dl.engine.file_manager import FileManager
from cosmo_dl.engine.types import DownloadResult
from cosmo_dl.progress import MultiFileProgress, fmt_bytes, fmt_speed

console = Console()

# Track whether the user has pressed Ctrl+C
_interrupted = False


@click.command("download")
@click.argument("target")
@click.option(
    "-w",
    "--workers",
    type=int,
    default=4,
    help="Chunk-parallel threads per file (for large files).",
)
@click.option(
    "-fw", "--file-workers", type=int, default=4, help="Number of files to download concurrently."
)
@click.option("-l", "--limit", default=None, help="Rate limit (e.g. '500KB/s', '2MB/s').")
@click.option(
    "-o",
    "--output",
    default="./cosmo-dl-downloads",
    help="Output directory (default: ./cosmo-dl-downloads).",
)
@click.option(
    "--resume/--no-resume", default=True, help="Resume partial downloads (default: enabled)."
)
@click.option(
    "--hash",
    "hash_algo",
    default=None,
    help="Hash algorithm to verify downloads (e.g. 'md5', 'sha256').",
)
@click.option(
    "--recursive/--no-recursive",
    default=False,
    help="Recursively explore and download from URL (default: disabled).",
)
@click.option(
    "--include",
    default="*",
    help="Pattern to include files when recursively exploring (default: '*').",
)
def download_cmd(
    target, workers, file_workers, limit, output, resume, hash_algo, recursive, include
):
    """Download simulation data from URL or source/dataset."""

    # ------------------------------------------------------------------
    # Install a SIGINT handler so a second Ctrl+C hard-exits immediately.
    # Using ``os._exit`` avoids the noisy threading-shutdown traceback
    # that Python prints when threads are joined during interpreter exit.
    # ------------------------------------------------------------------
    def _on_interrupt(signum, frame):
        global _interrupted
        if _interrupted:
            os._exit(130)
        _interrupted = True
        console.print("\n[yellow]Interrupted — waiting for in-flight work to finish...[/yellow]")
        console.print("[dim](Press Ctrl+C again to force quit)[/dim]")

    original_handler = signal.signal(signal.SIGINT, _on_interrupt)
    try:
        _do_download(
            target, workers, file_workers, limit, output, resume, hash_algo, recursive, include
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Download interrupted.[/yellow]")
        console.print("[dim]Partial progress saved — resume with the same command.[/dim]")
        os._exit(130)
    finally:
        signal.signal(signal.SIGINT, original_handler)


def _do_download(
    target, workers, file_workers, limit, output, resume, hash_algo, recursive, include
):
    """Actual download logic, factored out for clean interrupt handling."""
    if recursive and (target.startswith("http://") or target.startswith("https://")):
        # Extract a short label from the URL for the progress display
        _target_label = target.rstrip("/").rsplit("/", 1)[-1] or target

        with console.status(f"[bold blue]Scanning {_target_label}...[/bold blue]") as status:

            def _on_progress(files_found: int, total_bytes: int, scanning_url: str) -> None:
                if scanning_url:
                    # Just entered a new directory — show what we're scanning
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

            files = api_explore(target, recursive=True, include=include, on_progress=_on_progress)
        if not files:
            console.print("[yellow]No files found.[/yellow]")
            return
        console.print(f"Found [green]{len(files)}[/green] file(s). Starting download...\n")

        succeeded = 0
        failed = 0
        display = MultiFileProgress(console=console)

        with display:
            for entry in files:
                display.add_pending(entry.name)

            for entry in files:
                if _interrupted:
                    console.print("[yellow]Stopping — interrupt received.[/yellow]")
                    break

                local_path = FileManager.mirror_path(
                    entry.url,
                    base_url=target,
                    local_root=output,
                )
                local_path.parent.mkdir(parents=True, exist_ok=True)

                cb = display.start_file(entry.name, total_size=entry.size)
                try:
                    result = api_download(
                        entry.url,
                        local_path,
                        workers=workers,
                        file_workers=1,  # sequential per-file in recursive mode
                        rate_limit=limit,
                        resume=resume,
                        expected_hash=hash_algo,
                        progress=cb,
                    )
                    # When called per-file with a concrete dest, api_download
                    # always returns a single DownloadResult.
                    single: DownloadResult = result  # type: ignore[assignment]
                    if single.success:
                        succeeded += 1
                        display.complete_file(entry.name, success=True, actual_size=single.size)
                    else:
                        failed += 1
                        display.complete_file(entry.name, success=False)
                        console.print(f"  [red]FAILED:[/red] {entry.name}: {single.message}")
                except Exception as e:
                    failed += 1
                    display.complete_file(entry.name, success=False)
                    console.print(f"  [red]ERROR:[/red] {entry.name}: {e}")

        console.print(f"\nDone. [green]{succeeded}[/green] succeeded, [red]{failed}[/red] failed.")
    else:
        result = api_download(
            target,
            output_dir=output,
            workers=workers,
            file_workers=file_workers,
            rate_limit=limit,
            resume=resume,
            expected_hash=hash_algo,
        )
        if isinstance(result, list):
            for r in result:
                _print_result(r)
        else:
            _print_result(result)


def _print_result(r) -> None:
    """Print a single :class:`DownloadResult` with rich styling."""
    if r.success:
        size_str = fmt_bytes(r.size)
        speed_str = ""
        if r.speed > 0:
            speed_str = f" @ [cyan]{fmt_speed(r.speed)}[/cyan]"
        console.print(f"  [green]✓[/green] {r.local_path}  [dim]({size_str}{speed_str})[/dim]")
        if r.checksum:
            algo, _, digest = r.checksum.partition(":")
            console.print(f"    [dim]{algo}:[/dim] {digest}")
    else:
        console.print(f"  [red]✗ FAILED:[/red] {r.local_path}")
        console.print(f"    [red]{r.message}[/red]")
