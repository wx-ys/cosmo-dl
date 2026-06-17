"""Public Python API for cosmo-dl.

Provides the primary user-facing functions: :func:`list_sources`, :func:`explore`,
and :func:`download`.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from cosmo_dl.engine.downloader import Downloader, MB
from cosmo_dl.engine.explorer import URLExplorer
from cosmo_dl.engine.file_manager import FileManager
from cosmo_dl.engine.session import Session
from cosmo_dl.engine.types import AuthConfig, DownloadResult, FileEntry
from cosmo_dl.registry.registry import Registry
from tqdm import tqdm as _tqdm

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry = Registry()


def _get_auth_for_target(target: str) -> AuthConfig | None:
    """Look up the auth config for a source/dataset target.

    Returns None for raw URLs or sources without auth.
    """
    if target.startswith(("http://", "https://")):
        return None
    source_name = target.split("/", 1)[0]
    source = _registry.get(source_name)
    if source is not None and source.auth is not None:
        return source.auth  # type: ignore[return-value]
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
        if src is not None and hasattr(src, 'base_url') and src.base_url:
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


def download(
    target: str,
    dest: str | Path | None = None,
    *,
    resume: bool = True,
    workers: int = 4,
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
        single-threaded streaming.
    chunk_size : int
        Size of each download chunk in bytes (default 10 MiB).
    rate_limit : str or None
        Bandwidth cap, e.g. ``"10M"``, ``"500K"``.
    progress : callable or None
        Called as ``progress(downloaded_bytes, total_bytes)`` per file.
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
    urls = _resolve_target(target)

    # Look up auth from the registry if the target is a source/dataset
    auth = _get_auth_for_target(target)
    session = Session(auth=auth) if auth is not None else None

    try:
        downloader = Downloader(session=session)

        def _path_for_url(url: str) -> Path:
            if dest is not None and len(urls) == 1:
                return Path(dest)
            parsed = urlparse(url)
            filename = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "download"
            return Path(output_dir) / filename

        results: list[DownloadResult] = []
        url_iter = _tqdm(urls, desc="Files", unit="file", disable=len(urls) <= 1)
        for url in url_iter:
            local_dest = _path_for_url(url)
            fname = local_dest.name
            url_iter.set_postfix_str(fname[:40])
            result = downloader.download(
                url,
                local_dest,
                resume=resume,
                workers=workers,
                chunk_size=chunk_size,
                rate_limit=rate_limit,
                progress=progress,  # type: ignore[arg-type]
                expected_hash=expected_hash,
                expected_size=expected_size,
            )
            results.append(result)

        if len(results) == 1:
            return results[0]
        return results
    finally:
        if session is not None:
            session.close()
