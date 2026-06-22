"""CLI command: download."""
import click
from cosmo_dl.api import download as api_download, explore as api_explore
from cosmo_dl.engine.file_manager import FileManager

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
def download_cmd(target, workers, file_workers, limit, output, resume, hash_algo, recursive, include):
    """Download simulation data from URL or source/dataset."""
    if recursive and (target.startswith("http://") or target.startswith("https://")):
        click.echo(f"Exploring {target} ...")
        files = api_explore(target, recursive=True, include=include)
        if not files:
            click.echo("No files found.")
            return
        click.echo(f"Found {len(files)} file(s). Starting download...\n")
        from tqdm import tqdm
        succeeded = 0
        failed = 0
        with tqdm(total=len(files), desc="Files", unit="file") as pbar:
            for entry in files:
                local_path = FileManager.mirror_path(entry.url, base_url=target, local_root=output)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    result = api_download(entry.url, local_path, workers=workers, file_workers=file_workers, rate_limit=limit, resume=resume, expected_hash=hash_algo)
                    if result.success:
                        succeeded += 1
                    else:
                        failed += 1
                        click.echo(f"  FAILED: {entry.name}: {result.message}")
                except Exception as e:
                    failed += 1
                    click.echo(f"  ERROR: {entry.name}: {e}")
                pbar.update(1)
        click.echo(f"\nDone. {succeeded} succeeded, {failed} failed.")
    else:
        result = api_download(target, output_dir=output, workers=workers, file_workers=file_workers, rate_limit=limit, resume=resume, expected_hash=hash_algo)
        if isinstance(result, list):
            for r in result:
                status = "OK" if r.success else f"FAILED: {r.message}"
                click.echo(f"  {r.local_path}: {status}")
                if r.checksum:
                    click.echo(f"    {r.checksum}")
        else:
            status = "OK" if result.success else f"FAILED: {result.message}"
            click.echo(f"  {result.local_path}: {status}")
            if result.checksum:
                click.echo(f"    {result.checksum}")
