"""Core download engine with resume, multi-threading, rate limiting, and integrity."""
import os
import time
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from cosmo_dl.engine.types import DownloadResult
from cosmo_dl.engine.file_manager import FileManager

MB = 1_048_576


class Downloader:
    """Core download engine.

    Supports single-threaded streaming, multi-threaded parallel chunk downloads,
    resume via Range requests, bandwidth rate limiting, progress callbacks,
    and post-download integrity verification.

    Parameters
    ----------
    session : Session or None
        An existing :class:`cosmo_dl.engine.session.Session` instance.
        If *None*, a default session is created lazily.
    rate_limiter : RateLimiter or None
        A bandwidth limiter.  If *None*, no rate limiting is applied.
    """

    def __init__(self, session=None, rate_limiter=None):
        self._session = session
        self._rate_limiter = rate_limiter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        url: str,
        dest: str | Path,
        *,
        resume: bool = True,
        workers: int = 4,
        chunk_size: int = 10 * MB,
        rate_limit: str | None = None,
        progress: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> DownloadResult:
        """Download a single file from *url* to *dest*.

        Parameters
        ----------
        url : str
            Remote URL of the file.
        dest : str or Path
            Local filesystem path for the downloaded file.
        resume : bool
            If ``True`` (default), attempt to resume an interrupted
            download using existing partial data.
        workers : int
            Number of parallel download threads.  Set to ``1`` for
            single-threaded streaming.
        chunk_size : int
            Size of each download chunk in bytes (default 10 MiB).
        rate_limit : str or None
            Bandwidth cap e.g. ``"10M"``, ``"500K"``, ``"unlimited"``.
            Overrides the instance-level *rate_limiter* when provided.
        progress : callable or None
            Called as ``progress(downloaded_bytes, total_bytes)`` after
            each chunk is written.
        expected_hash : str or None
            Expected hash in ``"algo:hexdigest"`` form (e.g.
            ``"sha256:abc123"``) for post-download integrity check.
        expected_size : int or None
            Expected file size in bytes for post-download verification.

        Returns
        -------
        DownloadResult
        """
        dest = Path(dest)
        start_time = time.monotonic()

        try:
            # Resolve session -------------------------------------------------
            session = self._session
            if session is None:
                from cosmo_dl.engine.session import Session

                session = Session()

            # Resolve rate limiter --------------------------------------------
            limiter = self._rate_limiter
            if rate_limit is not None:
                from cosmo_dl.engine.rate_limiter import RateLimiter

                limiter = RateLimiter(rate_limit)

            # -- Create parent directories -----------------------------------
            dest.parent.mkdir(parents=True, exist_ok=True)

            # -- Determine resume state --------------------------------------
            part_path = Path(str(dest) + ".part")
            partial_size: int = 0

            if resume:
                if part_path.is_file():
                    partial_size = part_path.stat().st_size
                elif dest.is_file() and dest.stat().st_size > 0:
                    shutil.copy2(dest, part_path)
                    partial_size = dest.stat().st_size

            # -- Dispatch to engine ------------------------------------------
            if workers <= 1:
                total_downloaded = self._download_single(
                    session=session,
                    url=url,
                    part_path=part_path,
                    dest=dest,
                    partial_size=partial_size,
                    chunk_size=chunk_size,
                    limiter=limiter,
                    progress=progress,
                    start_time=start_time,
                    expected_size=expected_size,
                    expected_hash=expected_hash,
                )
            else:
                total_downloaded = self._download_multi(
                    session=session,
                    url=url,
                    part_path=part_path,
                    dest=dest,
                    partial_size=partial_size,
                    workers=workers,
                    chunk_size=chunk_size,
                    limiter=limiter,
                    progress=progress,
                    start_time=start_time,
                    expected_size=expected_size,
                    expected_hash=expected_hash,
                )

            # -- Post-download integrity check --------------------------------
            if not FileManager.check_integrity(
                dest,
                expected_size=expected_size,
                expected_hash=expected_hash,
            ):
                raise ValueError(
                    "Integrity check failed: size or hash does not match"
                )

            elapsed = time.monotonic() - start_time
            return DownloadResult(
                url=url,
                local_path=str(dest),
                size=total_downloaded,
                elapsed=elapsed,
                speed=total_downloaded / elapsed if elapsed > 0 else 0,
                success=True,
                message="OK",
            )

        except _AlreadyDownloaded as ad:
            return DownloadResult(
                url=url,
                local_path=str(dest),
                size=ad.size,
                elapsed=ad.elapsed,
                speed=ad.size / ad.elapsed if ad.elapsed > 0 else 0,
                success=True,
                message="Already downloaded",
            )
        except Exception as exc:
            elapsed = time.monotonic() - start_time
            return DownloadResult(
                url=url,
                local_path=str(dest),
                size=0,
                elapsed=elapsed,
                speed=0,
                success=False,
                message=str(exc),
            )

    # ------------------------------------------------------------------
    # Single-threaded engine
    # ------------------------------------------------------------------

    def _download_single(
        self,
        session,
        url: str,
        part_path: Path,
        dest: Path,
        partial_size: int,
        chunk_size: int,
        limiter,
        progress,
        start_time: float,
        expected_size: int | None,
        expected_hash: str | None,
    ) -> int:
        """Stream download into *part_path*, then rename to *dest*.

        Makes a single HTTP request (no separate HEAD) so that single-use
        mock responses work correctly in tests.
        """
        headers: dict[str, str] = {}
        if partial_size > 0:
            headers["Range"] = f"bytes={partial_size}-"

        mode = "ab" if partial_size > 0 else "wb"
        downloaded = partial_size

        with session.stream(url, headers=headers) as resp:
            # -- Status check -----------------------------------------------
            if resp.status_code == 404:
                raise RuntimeError("HTTP 404 Not Found")
            resp.raise_for_status()

            # -- Extract total size from response headers -------------------
            total: int = 0
            cr = resp.headers.get("Content-Range")
            if cr is not None:
                # "bytes 1000-4999/5000" -> total = 5000
                try:
                    total = int(cr.rsplit("/", 1)[-1])
                except (ValueError, IndexError):
                    pass
            if total <= 0:
                cl = resp.headers.get("Content-Length")
                if cl is not None:
                    total = int(cl)

            # -- Already-downloaded check -----------------------------------
            if total > 0 and dest.is_file() and dest.stat().st_size == total:
                if FileManager.check_integrity(
                    dest,
                    expected_size=expected_size,
                    expected_hash=expected_hash,
                ):
                    # Already have the complete file; skip download
                    if partial_size > 0 and part_path.is_file():
                        part_path.unlink()
                    elapsed = time.monotonic() - start_time
                    # Return result via exception since we're inside _download_single
                    raise _AlreadyDownloaded(total, elapsed)

            # -- Check if partial is already complete -----------------------
            if total > 0 and partial_size >= total:
                os.replace(part_path, dest)
                return total

            # -- Stream body to disk ----------------------------------------
            with open(part_path, mode) as fh:
                for chunk in resp.iter_bytes(chunk_size=chunk_size):
                    # Rate limiting
                    if limiter is not None:
                        wait = limiter.acquire(len(chunk))
                        if wait > 0:
                            time.sleep(wait)

                    fh.write(chunk)
                    downloaded += len(chunk)

                    # Progress callback
                    if progress is not None:
                        effective_total = total if total > 0 else downloaded
                        progress(downloaded, effective_total)

        # Rename .part -> dest
        os.replace(part_path, dest)

        return downloaded

    # ------------------------------------------------------------------
    # Multi-threaded engine
    # ------------------------------------------------------------------

    def _download_multi(
        self,
        session,
        url: str,
        part_path: Path,
        dest: Path,
        partial_size: int,
        workers: int,
        chunk_size: int,
        limiter,
        progress,
        start_time: float,
        expected_size: int | None,
        expected_hash: str | None,
    ) -> int:
        """Parallel chunk downloads assembled into *part_path*, then renamed to *dest*."""

        # -- HEAD request for remote metadata (needed for chunking) ---------
        total: int = 0
        try:
            head_resp = session.head(url)
            if head_resp.status_code == 404:
                raise RuntimeError("HTTP 404 Not Found")
            head_resp.raise_for_status()
            cl = head_resp.headers.get("Content-Length")
            if cl is not None:
                total = int(cl)
        except RuntimeError:
            raise
        except Exception:
            pass

        # Fallback: get size from a stream response
        if total <= 0:
            with session.stream(url) as resp:
                resp.raise_for_status()
                cl = resp.headers.get("Content-Length")
                cr = resp.headers.get("Content-Range")
                if cr is not None:
                    try:
                        total = int(cr.rsplit("/", 1)[-1])
                    except (ValueError, IndexError):
                        pass
                if total <= 0 and cl is not None:
                    total = int(cl)
            if total <= 0:
                raise RuntimeError(
                    "Cannot perform multi-threaded download: "
                    "server did not provide Content-Length"
                )

        # -- Already-downloaded check ---------------------------------------
        if dest.is_file() and dest.stat().st_size == total:
            if FileManager.check_integrity(
                dest,
                expected_size=expected_size,
                expected_hash=expected_hash,
            ):
                raise _AlreadyDownloaded(total, time.monotonic() - start_time)

        # -- Sanity-check partial data --------------------------------------
        if partial_size >= total:
            os.replace(part_path, dest)
            return total

        # -- Calculate chunk boundaries -------------------------------------
        num_chunks = max(workers, 1)
        actual_chunk_size = max(chunk_size, (total + num_chunks - 1) // num_chunks)
        num_chunks = (total + actual_chunk_size - 1) // actual_chunk_size
        num_chunks = min(num_chunks, workers * 4)

        chunks = []
        for i in range(num_chunks):
            start = i * actual_chunk_size
            end = min(start + actual_chunk_size, total) - 1
            if start < total:
                chunks.append((i, start, end))

        # -- Download chunks in parallel ------------------------------------
        chunk_data: dict[int, bytes] = {}
        downloaded = partial_size

        def _fetch_chunk(idx: int, start: int, end: int):
            req_headers = {"Range": f"bytes={start}-{end}"}
            buf = bytearray()
            with session.stream(url, headers=req_headers) as resp:
                resp.raise_for_status()
                for piece in resp.iter_bytes(chunk_size=min(chunk_size, 1024 * 1024)):
                    buf.extend(piece)
            return idx, bytes(buf)

        with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
            futures = [
                executor.submit(_fetch_chunk, idx, start, end)
                for idx, start, end in chunks
            ]
            for future in as_completed(futures):
                idx, data = future.result()

                # Rate limiting
                if limiter is not None:
                    wait = limiter.acquire(len(data))
                    if wait > 0:
                        time.sleep(wait)

                chunk_data[idx] = data
                downloaded += len(data)

                # Progress callback
                if progress is not None:
                    progress(downloaded, total)

        # -- Assemble chunks in order into .part file -----------------------
        with open(part_path, "wb") as fh:
            for i in range(len(chunks)):
                fh.write(chunk_data[i])

        # Rename .part -> dest
        os.replace(part_path, dest)

        return downloaded


class _AlreadyDownloaded(Exception):
    """Internal sentinel: file was already fully downloaded."""

    def __init__(self, size: int, elapsed: float) -> None:
        self.size = size
        self.elapsed = elapsed
