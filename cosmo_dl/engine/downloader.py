"""Core download engine with resume, multi-threading, rate limiting, and integrity."""
import os
import re
import time
import shutil
import email.utils
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from cosmo_dl.engine.types import DownloadResult
from cosmo_dl.engine.file_manager import FileManager

MB = 1_048_576

# Pattern for Content-Disposition filename extraction (RFC 6266 / RFC 5987)
_CD_FILENAME_RE = re.compile(
    r"""filename\*?=(?:UTF-8''([^;]*)|"([^"]*)"|'([^']*)'|([^;]*))\s*;?""",
    re.IGNORECASE,
)


def _parse_content_disposition(header: str) -> str | None:
    """Extract the filename from a Content-Disposition header value.

    Handles RFC 5987 ``filename*=UTF-8''...`` encoding and plain
    ``filename="..."`` / ``filename=...`` forms.
    """
    if not header:
        return None
    for match in _CD_FILENAME_RE.finditer(header):
        for group in match.groups():
            if group:
                return group.strip()
    # Fallback: simple split
    if 'filename=' in header.lower():
        idx = header.lower().find('filename=')
        if idx >= 0:
            rest = header[idx + 9:]  # skip "filename="
            if header[idx + 8] == '*':
                rest = rest.split("''", 1)
                rest = rest[1] if len(rest) > 1 else rest[0]
            rest = rest.strip().split(';', 1)[0].strip()
            if rest and rest[0] in ('"', "'") and rest[-1] == rest[0]:
                rest = rest[1:-1]
            if rest:
                return rest
    return None


def _apply_last_modified(dest: Path, headers) -> None:
    """Set the local file's mtime from the ``Last-Modified`` response header."""
    lm = headers.get("Last-Modified")
    if not lm:
        return
    try:
        t_struct = time.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z")
        ts = time.mktime(t_struct)
        os.utime(dest, (ts, ts))
    except Exception:
        pass


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
                total_downloaded, final_dest = self._download_single(
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
                total_downloaded, final_dest = self._download_multi(
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
                final_dest,
                expected_size=expected_size,
                expected_hash=expected_hash,
            ):
                raise ValueError(
                    "Integrity check failed: size or hash does not match"
                )

            elapsed = time.monotonic() - start_time
            return DownloadResult(
                url=url,
                local_path=str(final_dest),
                size=total_downloaded,
                elapsed=elapsed,
                speed=total_downloaded / elapsed if elapsed > 0 else 0,
                success=True,
                message="OK",
            )

        except _AlreadyDownloaded as ad:
            return DownloadResult(
                url=url,
                local_path=str(ad.dest),
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
    ) -> tuple[int, Path]:
        """Stream download into *part_path*, then rename to *dest*.

        Returns ``(bytes_downloaded, final_dest_path)``.  The final path may
        differ from *dest* when the server provides a different filename via
        the ``Content-Disposition`` header.
        """
        headers: dict[str, str] = {}
        if partial_size > 0:
            headers["Range"] = f"bytes={partial_size}-"

        mode = "ab" if partial_size > 0 else "wb"
        downloaded = partial_size
        response_headers = None

        with session.stream(url, headers=headers) as resp:
            # -- Status check -----------------------------------------------
            if resp.status_code == 404:
                raise RuntimeError("HTTP 404 Not Found")
            resp.raise_for_status()

            # Save headers for post-download processing
            response_headers = resp.headers

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

            # -- Extract server-provided filename ----------------------------
            cd_filename = _parse_content_disposition(
                resp.headers.get("Content-Disposition", "")
            )
            if cd_filename:
                dest = dest.parent / cd_filename

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
                    raise _AlreadyDownloaded(total, elapsed, dest)

            # -- Check if partial is already complete -----------------------
            if total > 0 and partial_size >= total:
                os.replace(part_path, dest)
                return total, dest

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

        # Preserve server file modification time
        if response_headers is not None:
            _apply_last_modified(dest, response_headers)

        return downloaded, dest

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
    ) -> tuple[int, Path]:
        """Parallel chunk downloads assembled into *part_path*, then renamed to *dest*.

        Returns ``(bytes_downloaded, final_dest_path)``.
        """

        # -- Gather remote metadata: HEAD first, then stream GET fallback ---
        total: int = 0
        cd_filename: str | None = None
        head_headers = None

        # Phase 1: HEAD request for Content-Length + Content-Disposition
        try:
            head_resp = session.head(url)
            if head_resp.status_code == 404:
                raise RuntimeError("HTTP 404 Not Found")
            head_resp.raise_for_status()
            head_headers = head_resp.headers
            cl = head_resp.headers.get("Content-Length")
            if cl is not None:
                total = int(cl)
            cd_filename = _parse_content_disposition(
                head_resp.headers.get("Content-Disposition", "")
            )
        except RuntimeError:
            raise
        except Exception:
            pass

        # Phase 2: fallback stream GET when HEAD didn't give us size
        if total <= 0:
            with session.stream(url) as resp:
                resp.raise_for_status()
                if head_headers is None:
                    head_headers = resp.headers
                cl = resp.headers.get("Content-Length")
                cr = resp.headers.get("Content-Range")
                if cr is not None:
                    try:
                        total = int(cr.rsplit("/", 1)[-1])
                    except (ValueError, IndexError):
                        pass
                if total <= 0 and cl is not None:
                    total = int(cl)
                # Also extract Content-Disposition from this GET response
                if cd_filename is None:
                    cd_filename = _parse_content_disposition(
                        resp.headers.get("Content-Disposition", "")
                    )
            if total <= 0:
                raise RuntimeError(
                    "Cannot perform multi-threaded download: "
                    "server did not provide Content-Length"
                )

        # Phase 3: if HEAD gave us size but NOT filename, probe with a tiny
        #          Range GET (bytes=0-0) to get the Content-Disposition header.
        if cd_filename is None and total > 0:
            try:
                with session.stream(url, headers={"Range": "bytes=0-0"}) as probe:
                    probe.raise_for_status()
                    cd_filename = _parse_content_disposition(
                        probe.headers.get("Content-Disposition", "")
                    )
                    if head_headers is None:
                        head_headers = probe.headers
            except Exception:
                pass

        # Apply Content-Disposition filename if available
        if cd_filename:
            dest = dest.parent / cd_filename

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
            return total, dest

        # -- Calculate chunk boundaries -------------------------------------
        # Use smaller chunks for finer-grained progress reporting while
        # still keeping overhead reasonable (min 1 MiB per chunk).
        num_chunks = max(workers * 4, 8)
        actual_chunk_size = max(
            1024 * 1024, (total + num_chunks - 1) // num_chunks,
        )
        num_chunks = (total + actual_chunk_size - 1) // actual_chunk_size
        num_chunks = min(num_chunks, workers * 8)

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

        # Preserve server file modification time
        if head_headers is not None:
            _apply_last_modified(dest, head_headers)

        return downloaded, dest


class _AlreadyDownloaded(Exception):
    """Internal sentinel: file was already fully downloaded."""

    def __init__(self, size: int, elapsed: float, dest: Path) -> None:
        self.size = size
        self.elapsed = elapsed
        self.dest = dest
