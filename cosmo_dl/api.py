"""Public Python API for cosmo-dl.

Provides the primary user-facing functions: :func:`list_sources`, :func:`explore`,
and :func:`download`.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console

from cosmo_dl.engine.downloader import MB, Downloader
from cosmo_dl.engine.explorer import URLExplorer
from cosmo_dl.engine.session import Session
from cosmo_dl.engine.types import AuthConfig, DownloadResult, FileEntry
from cosmo_dl.progress import MultiFileProgress, SingleFileProgress
from cosmo_dl.registry.registry import Registry

console = Console()

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry = Registry()


def _get_auth_for_target(target: str) -> AuthConfig | None:
    """Look up the auth config for a source/dataset target.

    Returns None for raw URLs or sources without auth.
    Uses direct tree lookup to avoid triggering legacy conversion + lazy loading.
    """
    if target.startswith(("http://", "https://")):
        return None
    source_name = target.split("/", 1)[0]
    root = _registry._roots.get(source_name)
    if root is not None and root.auth is not None:
        return root.auth  # type: ignore[return-value]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_sources() -> list[str]:
    """Return a sorted list of registered simulation source names.

    Returns
    -------
    list[str]
        Alphabetically sorted list of source names known to the registry
        (built-in sources plus any user-defined sources from YAML).
    """
    return _registry.list()


def _resolve_target(target: str) -> list[str]:
    """Resolve a source name, dataset identifier, or raw URL into concrete URLs.

    Parameters
    ----------
    target : str
        One of:

        - A raw URL (``http://`` or ``https://``) — returned as-is.
        - A source name (no ``/``) — returns the source's base URL.
        - A ``Source/dataset`` identifier — resolves the dataset to one or
          more concrete URLs via the source definition.

    Returns
    -------
    list[str]
        Concrete HTTPS URLs.
    """
    return _registry.resolve(target)


def _resolve_target_with_paths(target: str) -> list[tuple[str, str | None]]:
    """Resolve a target into ``(URL, download_relpath)`` pairs.

    Like :func:`_resolve_target` but also returns the configured
    download relative path for each URL.  Raw URLs get ``None`` paths.
    """
    if target.startswith(("http://", "https://")):
        return [(target, None)]

    # Try tree navigation
    node = _registry.get_node(target)
    if node is not None:
        return node.resolve_with_relpath()

    # Legacy fallback
    if "/" in target:
        source_name, dataset = target.split("/", 1)
        src = _registry._roots.get(source_name)
        if src is not None and hasattr(src, "base_url") and src.base_url:
            child = src.get_child(dataset)
            if child is not None:
                return child.resolve_with_relpath()
            raise KeyError(f"Unknown dataset: {dataset!r}")
        raise ValueError(f"Unknown source: {source_name!r}")

    raise ValueError(f"Unknown target: {target!r}")


def explore(
    url: str,
    *,
    recursive: bool = True,
    max_depth: int | None = None,
    include: str = "*",
    exclude: str | None = None,
    auth: AuthConfig | None = None,
) -> list[FileEntry]:
    """Discover files at *url* by parsing HTML directory listings or JSON APIs.

    Parameters
    ----------
    url : str
        Base URL pointing to an HTML directory listing or JSON API endpoint.
    recursive : bool
        When ``True`` (default), recurse into sub-directories.
    max_depth : int or None
        Maximum recursion depth.  ``None`` means unlimited.
    include : str
        ``fnmatch``-style glob for names to *include* (default ``"*"``).
    exclude : str or None
        ``fnmatch``-style glob for names to *exclude*.
    auth : AuthConfig or None
        Optional authentication for the HTTP requests (e.g. TNG API key).

    Returns
    -------
    list[FileEntry]
        Matching file and directory entries.
    """
    session = Session(auth=auth) if auth is not None else None
    explorer = URLExplorer(session=session)
    try:
        return explorer.explore(
            url,
            recursive=recursive,
            max_depth=max_depth,
            include=include,
            exclude=exclude,
        )
    finally:
        if session is not None:
            session.close()


# Reused in download_cmd.py
def _fmt_speed(bytes_per_second: float) -> str:
    """Format a bytes-per-second rate as a human-readable string."""
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f} MB/s"
    elif bytes_per_second >= 1024:
        return f"{bytes_per_second / 1024:.0f} KB/s"
    elif bytes_per_second > 0:
        return f"{bytes_per_second:.0f} B/s"
    return ""


def download(
    target: str,
    dest: str | Path | None = None,
    *,
    resume: bool = True,
    workers: int = 4,
    file_workers: int = 4,
    chunk_size: int = 10 * MB,
    rate_limit: str | None = None,
    progress: object = None,
    expected_hash: str | None = None,
    expected_size: int | None = None,
    output_dir: str = "./cosmo-dl-downloads",
) -> DownloadResult | list[DownloadResult]:
    """Download one or more files from *target*.

    Parameters
    ----------
    target : str
        A raw URL, a source name, or a ``Source/dataset`` identifier.
    dest : str, Path, or None
        Local destination path.  When *None*, the filename is derived from
        the URL and placed under *output_dir*.  For multi-URL targets
        (e.g. dataset patterns), *dest* is ignored and each file is saved
        under *output_dir*.
    resume : bool
        If ``True`` (default), attempt to resume an interrupted download.
    workers : int
        Number of parallel download threads per file.  Set to ``1`` for
        single-threaded streaming.  When *file_workers* > 1 and downloading
        multiple files, this is automatically reduced to 1 per file (file-level
        parallelism is more efficient for many small files).
    file_workers : int
        Number of files to download concurrently.  Set to ``1`` for sequential
        downloads (current behavior).  Default is 4.
    chunk_size : int
        Size of each download chunk in bytes (default 10 MiB).
    rate_limit : str or None
        Bandwidth cap, e.g. ``"10M"``, ``"500K"``.  When downloading
        multiple files concurrently, this cap is shared across all files.
    progress : callable or None
        Called as ``progress(downloaded_bytes, total_bytes)`` per file.
        Ignored in concurrent mode (*file_workers* > 1).
    expected_hash : str or None
        Expected hash in ``"algo:hexdigest"`` form.
    expected_size : int or None
        Expected file size in bytes.
    output_dir : str
        Directory for auto-derived download paths when *dest* is ``None``.
        Defaults to ``"./cosmo-dl-downloads"``.

    Returns
    -------
    DownloadResult or list[DownloadResult]
        A single result when downloading one URL; a list when downloading
        multiple URLs.
    """
    # Use resolve_with_relpath to get URL + download_relpath pairs
    pairs = _resolve_target_with_paths(target)
    # Fall back to plain URL resolution for backward compat
    if not pairs:
        urls = _resolve_target(target)
        pairs = [(u, None) for u in urls]

    # Look up auth from the registry if the target is a source/dataset.
    # TNG API file URLs (e.g. www.tng-project.org/api/.../files/...) require
    # the ``api-key`` header for authentication.  The API may redirect to a
    # data server with a ``?token=...`` query parameter; ``requests``
    # correctly strips the ``api-key`` header on cross-origin redirects.
    auth = _get_auth_for_target(target)
    session = Session(auth=auth) if auth is not None else Session()

    # Create one shared rate limiter so concurrent file downloads honour
    # a single global bandwidth cap, not N independent caps.
    shared_limiter = None
    if rate_limit is not None:
        from cosmo_dl.engine.rate_limiter import RateLimiter

        shared_limiter = RateLimiter(rate_limit)

    try:
        downloader = Downloader(session=session, rate_limiter=shared_limiter)

        def _path_for_pair(url: str, relpath: str | None) -> Path:
            if dest is not None and len(pairs) == 1:
                return Path(dest)
            if relpath:
                if "/" in relpath:
                    relpath = relpath.split("/", 1)[1]
                return Path(output_dir) / relpath
            parsed = urlparse(url)
            filename = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "download"
            return Path(output_dir) / filename

        # Pre-compute all local destinations
        url_dests: list[tuple[str, str | None, Path]] = []
        for url, relpath in pairs:
            url_dests.append((url, relpath, _path_for_pair(url, relpath)))

        # Auto-adjust per-file workers when using file-level concurrency.
        # File-level parallelism is more efficient for many small files;
        # chunk-level multi-threading is only beneficial for large files.
        per_file_workers = 1 if (file_workers > 1 and len(url_dests) > 1) else workers

        # --- Sequential path (single file or file_workers=1) ---------------
        if file_workers <= 1 or len(url_dests) <= 1:
            results: list[DownloadResult] = []

            for url, _relpath, local_dest in url_dests:
                fname = local_dest.name

                if progress is not None:
                    # User-provided callback — use directly, no built-in display.
                    cb = progress
                    file_display = None
                else:
                    file_display = SingleFileProgress(
                        fname,
                        worker_count=per_file_workers,
                        console=console,
                    )
                    file_display.__enter__()
                    cb = file_display.callback

                try:
                    result = downloader.download(
                        url,
                        local_dest,
                        resume=resume,
                        workers=per_file_workers,
                        chunk_size=chunk_size,
                        progress=cb,  # type: ignore[arg-type]
                        expected_hash=expected_hash,
                        expected_size=expected_size,
                    )
                finally:
                    if file_display is not None:
                        file_display.__exit__(None, None, None)

                if not result.success:
                    console.print(f"  [red]FAIL[/red]  {local_dest}\n        {result.message}")
                results.append(result)

            if len(results) == 1:
                return results[0]
            return results

        # --- Concurrent path (file_workers > 1, multiple files) -----------
        concurrent_results: list[DownloadResult] = []
        results_lock = threading.Lock()

        # ------------------------------------------------------------------
        # Pre-fetch Content-Length for every URL via parallel HEAD requests
        # so each file bar and the aggregate bar can show real totals.
        # ------------------------------------------------------------------
        grand_total = 0
        total_known = True
        file_sizes: dict[str, int | None] = {}

        def _fetch_content_length(url: str) -> int | None:
            """Return Content-Length for *url* (HEAD request), or None."""
            try:
                resp = session.head(url)
                cl = resp.headers.get("Content-Length")
                if cl is not None:
                    return int(cl)
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=min(file_workers, len(url_dests))) as head_executor:
            size_futures = {
                head_executor.submit(_fetch_content_length, url): (url, local_dest)
                for url, _, local_dest in url_dests
            }
            for head_future in as_completed(size_futures):
                url, local_dest = size_futures[head_future]
                size = head_future.result()
                file_sizes[local_dest.name] = size
                if size is not None:
                    grand_total += size
                else:
                    total_known = False

        # -- Build Docker-pull-style display ---------------------------------
        display = MultiFileProgress(
            total_bytes=grand_total,
            total_known=total_known,
            console=console,
        )
        for _, _relpath, local_dest in url_dests:
            display.add_pending(local_dest.name)

        try:
            with display, ThreadPoolExecutor(max_workers=file_workers) as executor:
                future_to_info: dict = {}
                for url, _relpath, local_dest in url_dests:
                    local_dest.parent.mkdir(parents=True, exist_ok=True)
                    total_size = file_sizes.get(local_dest.name)
                    cb = display.start_file(local_dest.name, total_size=total_size)
                    fut = executor.submit(
                        downloader.download,
                        url,
                        local_dest,
                        resume=resume,
                        workers=per_file_workers,
                        chunk_size=chunk_size,
                        progress=cb,
                        expected_hash=expected_hash,
                        expected_size=expected_size,
                    )
                    future_to_info[fut] = (url, local_dest)

                for future in as_completed(future_to_info):
                    url, local_dest = future_to_info[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = DownloadResult(
                            url=url,
                            local_path=str(local_dest),
                            size=0,
                            elapsed=0,
                            speed=0,
                            success=False,
                            message=str(exc),
                        )

                    with results_lock:
                        if result.success:
                            display.complete_file_with_size(
                                local_dest.name,
                                success=True,
                                actual_size=result.size,
                            )
                        else:
                            display.complete_file(local_dest.name, success=False)
                            console.print(
                                f"  [red]FAIL[/red]  {local_dest}\n        {result.message}"
                            )
                        concurrent_results.append(result)
        finally:
            pass  # display.__exit__ already called by the `with display:` block

        if len(concurrent_results) == 1:
            return concurrent_results[0]
        return concurrent_results
    finally:
        if session is not None:
            session.close()
