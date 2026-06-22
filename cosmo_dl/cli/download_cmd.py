"""CLI command: download."""
from __future__ import annotations

import os
import signal

import rich_click as click
from rich.console import Console

from cosmo_dl.api import download as api_download
from cosmo_dl.api import explore as api_explore
from cosmo_dl.engine.file_manager import FileManager

console = Console()

# Track whether the user has pressed Ctrl+C
_interrupted = False


@click.command("download")
@click.argument("target")
@click.option("-w", "--workers", type=int, default=4,
              help="Chunk-parallel threads per file (for large files).")
@click.option("-fw", "--file-workers", type=int, default=4,
              help="Number of files to download concurrently.")
@click.option("-l", "--limit", default=None,
              help="Rate limit (e.g. '500KB/s', '2MB/s').")
@click.option("-o", "--output", default="./cosmo-dl-downloads",
              help="Output directory (default: ./cosmo-dl-downloads).")
@click.option("--resume/--no-resume", default=True,
              help="Resume partial downloads (default: enabled).")
@click.option("--hash", "hash_algo", default=None,
              help="Hash algorithm to verify downloads (e.g. 'md5', 'sha256').")
@click.option("--recursive/--no-recursive", default=False,
              help="Recursively explore and download from URL (default: disabled).")
@click.option("--include", default="*",
              help="Pattern to include files when recursively exploring (default: '*').")
def download_cmd(target, workers, file_workers, limit, output, resume,
                 hash_algo, recursive, include):
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
        console.print(
            "\n[yellow]Interrupted — waiting for in-flight work to finish...[/yellow]"
        )
        console.print("[dim](Press Ctrl+C again to force quit)[/dim]")

    original_handler = signal.signal(signal.SIGINT, _on_interrupt)
    try:
        _do_download(target, workers, file_workers, limit, output, resume,
                     hash_algo, recursive, include)
    except KeyboardInterrupt:
        console.print(
            "\n[yellow]Download interrupted.[/yellow]"
        )
        console.print(
            "[dim]Partial progress saved — resume with the same command.[/dim]"
        )
        os._exit(130)
    finally:
        signal.signal(signal.SIGINT, original_handler)


def _do_download(target, workers, file_workers, limit, output, resume,
                 hash_algo, recursive, include):
    """Actual download logic, factored out for clean interrupt handling."""
    if recursive and (target.startswith("http://") or target.startswith("https://")):
        console.print(f"[dim]Exploring {target} ...[/dim]")
        files = api_explore(target, recursive=True, include=include)
        if not files:
            console.print("[yellow]No files found.[/yellow]")
            return
        console.print(f"Found [green]{len(files)}[/green] file(s). Starting download...\n")
        from tqdm import tqdm
        succeeded = 0
        failed = 0
        with tqdm(total=len(files), desc="Files", unit="file") as pbar:
            for entry in files:
                local_path = FileManager.mirror_path(
                    entry.url, base_url=target, local_root=output,
                )
                local_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    result = api_download(
                        entry.url, local_path,
                        workers=workers, file_workers=file_workers,
                        rate_limit=limit, resume=resume,
                        expected_hash=hash_algo,
                    )
                    if result.success:
                        succeeded += 1
                    else:
                        failed += 1
                        console.print(f"  [red]FAILED:[/red] {entry.name}: {result.message}")
                except Exception as e:
                    failed += 1
                    console.print(f"  [red]ERROR:[/red] {entry.name}: {e}")
                pbar.update(1)
        console.print(f"\nDone. [green]{succeeded}[/green] succeeded, [red]{failed}[/red] failed.")
    else:
        result = api_download(
            target, output_dir=output,
            workers=workers, file_workers=file_workers,
            rate_limit=limit, resume=resume,
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
        size_str = _fmt_bytes(r.size)
        speed_str = ""
        if r.speed > 0:
            speed_str = f" @ [cyan]{_fmt_speed(r.speed)}[/cyan]"
        console.print(
            f"  [green]✓[/green] {r.local_path}  "
            f"[dim]({size_str}{speed_str})[/dim]"
        )
        if r.checksum:
            algo, _, digest = r.checksum.partition(":")
            console.print(f"    [dim]{algo}:[/dim] {digest}")
    else:
        console.print(f"  [red]✗ FAILED:[/red] {r.local_path}")
        console.print(f"    [red]{r.message}[/red]")


def _fmt_bytes(size: int) -> str:
    """Format a byte count as a human-readable string."""
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024**3):.1f} GiB"
    elif size >= 1024 * 1024:
        return f"{size / (1024**2):.1f} MiB"
    elif size >= 1024:
        return f"{size / 1024:.0f} KiB"
    return f"{size} B"


def _fmt_speed(bytes_per_second: float) -> str:
    """Format a bytes-per-second rate as a human-readable string."""
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f} MB/s"
    elif bytes_per_second >= 1024:
        return f"{bytes_per_second / 1024:.0f} KB/s"
    elif bytes_per_second > 0:
        return f"{bytes_per_second:.0f} B/s"
    return ""
