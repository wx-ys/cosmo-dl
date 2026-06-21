"""Core download engine with resume, multi-threading, rate limiting, and integrity."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import shutil
import email.utils
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from cosmo_dl.engine.types import DownloadResult
from cosmo_dl.engine.file_manager import FileManager

logger = logging.getLogger(__name__)

MB = 1_048_576


def _is_sparse_file(filepath: Path) -> bool:
    """Check whether *filepath* is sparse (apparent size > disk blocks).

    On most Linux filesystems :func:`os.truncate` creates a sparse file
    — the apparent size is large but actual disk usage is near zero.
    This helper detects such pre-allocated-but-unwritten files so the
    downloader can restart them from scratch instead of treating them
    as complete.
    """
    try:
        stat = filepath.stat()
        apparent = stat.st_size
        if apparent <= 0:
            return False
        # st_blocks is reported in 512-byte units
        actual = stat.st_blocks * 512
        # Allow a small tolerance so nearly-complete downloads aren't discarded
        return actual < apparent * 0.8
    except Exception:
        return False

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


def _apply_last_modified(dest: Path, last_modified: str | None) -> None:
    """Set the local file's mtime from a ``Last-Modified`` header value.

    Parameters
    ----------
    dest : Path
        Local file whose mtime should be updated.
    last_modified : str or None
        Raw ``Last-Modified`` header value (RFC 2822).  If *None* or
        empty, this function is a no-op.
    """
    if not last_modified:
        return
    try:
        dt = email.utils.parsedate_to_datetime(last_modified)
        if dt is not None:
            ts = dt.timestamp()
            os.utime(dest, (ts, ts))
    except Exception:
        pass


@dataclass(slots=True)
class _Metadata:
    """Parsed remote file metadata from HTTP probes.

    Attributes
    ----------
    total : int
        Remote file size in bytes.  0 means unknown.
    cd_filename : str or None
        Filename extracted from ``Content-Disposition`` header, if any.
    last_modified : str or None
        Raw ``Last-Modified`` header value, if any.
    """

    total: int
    cd_filename: str | None = None
    last_modified: str | None = None


def _fetch_chunk(
    session,
    url: str,
    chunk_io_size: int,
    idx: int,
    start: int,
    end: int,
    limiter=None,
    on_read: Callable[[int], None] | None = None,
) -> tuple[int, bytes]:
    """Fetch a single byte range from *url*.

    Parameters
    ----------
    session :
        A :class:`~cosmo_dl.engine.session.Session` instance.
    url : str
        Download URL.
    chunk_io_size : int
        I/O read size passed to :meth:`iter_bytes`.
    idx : int
        Zero-based chunk index (for ordered assembly).
    start : int
        Start byte offset (inclusive).
    end : int
        End byte offset (inclusive).
    limiter : RateLimiter or None
        Optional bandwidth limiter.  Rate limiting is applied **during**
        network read so that the transfer itself is throttled.
    on_read : callable or None
        Called as ``on_read(n_bytes)`` after each successful read from
        the stream, for fine-grained progress reporting.

    Returns
    -------
    tuple[int, bytes]
        ``(idx, chunk_bytes)``.
    """
    req_headers = {"Range": f"bytes={start}-{end}"}
    buf = bytearray()
    with session.stream(url, headers=req_headers) as resp:
        resp.raise_for_status()
        for piece in resp.iter_bytes(
            chunk_size=min(chunk_io_size, 1024 * 1024),
        ):
            if limiter is not None:
                wait = limiter.acquire(len(piece))
                if wait > 0:
                    time.sleep(wait)
            buf.extend(piece)
            if on_read is not None:
                on_read(len(piece))
    return idx, bytes(buf)


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
                    # Guard against sparse .part files left by interrupted
                    # multi-threaded downloads (truncate pre-allocates the
                    # full size but writes very little data).
                    if partial_size > 0 and _is_sparse_file(part_path):
                        logger.warning(
                            "Removing stale .part file from interrupted "
                            "multi-threaded download (%s bytes apparent, "
                            "but file is sparse — restarting from scratch).",
                            partial_size,
                        )
                        part_path.unlink()
                        partial_size = 0
                elif dest.is_file() and dest.stat().st_size > 0:
                    shutil.copy2(dest, part_path)
                    partial_size = dest.stat().st_size

            # -- Gather remote metadata ---------------------------------------
            # Phase 1: HEAD always — cheapest probe for Content-Length and
            # Content-Disposition.  If the server provides Content-Length
            # and multi-threading is requested, a follow-up stream GET +
            # Range probe fills in any missing CD / Last-Modified headers.
            metadata = self._gather_metadata(
                session, url, fallback_get=False,
            )

            # When Content-Length is known, multi-threaded downloads can
            # partition the file into byte-range chunks.  Follow up with
            # stream + Range probes to learn Content-Disposition /
            # Last-Modified if HEAD did not provide them.
            if metadata.total > 0 and workers > 1:
                metadata = self._gather_metadata(
                    session, url, fallback_get=True,
                )
            elif metadata.total <= 0 and workers > 1:
                logger.warning(
                    "Server did not provide Content-Length; "
                    "falling back to single-threaded download"
                )

            # Apply server-provided filename from Content-Disposition.
            # When HEAD returned Content-Disposition we already know the real
            # filename and can perform the standard pre-flight checks.
            # Otherwise (common for TNG where HEAD omits Content-Disposition),
            # defer the existence / partial-complete checks to
            # _download_single, which will learn the real filename from the
            # GET response headers.
            cd_filename_known = metadata.cd_filename is not None
            if metadata.cd_filename:
                dest = dest.parent / metadata.cd_filename

            if cd_filename_known:
                # -- Pre-download checks (real filename known) -----------------
                self._check_already_downloaded(
                    dest=dest,
                    total=metadata.total,
                    expected_size=expected_size,
                    expected_hash=expected_hash,
                    part_path=part_path,
                    partial_size=partial_size,
                    start_time=start_time,
                )

                pc_result = self._check_partial_complete(
                    part_path, dest, partial_size, metadata.total,
                )
                if pc_result is not None:
                    total_downloaded, final_dest = pc_result
                elif workers <= 1 or metadata.total <= 0:
                    total_downloaded, final_dest = self._download_single(
                        session=session,
                        url=url,
                        part_path=part_path,
                        dest=dest,
                        partial_size=partial_size,
                        chunk_size=chunk_size,
                        limiter=limiter,
                        progress=progress,
                        metadata=metadata,
                        start_time=start_time,
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
                        metadata=metadata,
                    )
            else:
                # cd_filename unknown — defer to _download_single which will
                # learn the real filename from the GET response and handle:
                #   1. real-name file exists, complete → skip
                #   2. real-name file exists, mtime wrong → fix mtime, skip
                #   3. URL-name file exists → rename to real name, fix mtime, skip
                total_downloaded, final_dest = self._download_single(
                    session=session,
                    url=url,
                    part_path=part_path,
                    dest=dest,
                    partial_size=partial_size,
                    chunk_size=chunk_size,
                    limiter=limiter,
                    progress=progress,
                    metadata=metadata,
                    start_time=start_time,
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
    # Metadata gathering
    # ------------------------------------------------------------------

    @staticmethod
    def _gather_metadata(session, url: str, *, fallback_get: bool = True) -> _Metadata:
        """Probe *url* to determine file size, filename, and modification time.

        Uses an escalating three-phase strategy so that the cheapest
        request (HEAD) is tried first, falling back to heavier probes
        only when necessary.  When both Phase 2 (stream GET) and
        Phase 3 (Range probe) are required they are issued in parallel
        to avoid an extra sequential round-trip.

        When *fallback_get* is ``False`` (single-threaded downloads),
        only Phase 1 (HEAD) is executed.  The stream GET response is
        preserved for the actual download.

        Returns
        -------
        _Metadata
        """
        total: int = 0
        cd_filename: str | None = None
        last_modified: str | None = None

        # Phase 1: HEAD — cheapest, only headers
        try:
            head_resp = session.head(url)
            if head_resp.status_code == 404:
                raise RuntimeError("HTTP 404 Not Found")
            head_resp.raise_for_status()

            cl = head_resp.headers.get("Content-Length")
            if cl is not None:
                total = int(cl)
            cd_filename = _parse_content_disposition(
                head_resp.headers.get("Content-Disposition", "")
            )
            last_modified = head_resp.headers.get("Last-Modified")
        except RuntimeError:
            raise
        except Exception:
            pass

        # Single-threaded: stop here — the GET response must be preserved
        # for _download_single to consume.
        if not fallback_get:
            return _Metadata(
                total=total,
                cd_filename=cd_filename,
                last_modified=last_modified,
            )

        # ------------------------------------------------------------------
        # Determine which follow-up probes are needed
        # ------------------------------------------------------------------
        need_stream_get = (total <= 0)                        # Phase 2
        need_range = (cd_filename is None or last_modified is None)  # Phase 3

        def _stream_get_probe():
            """Phase 2: stream GET to learn total size (and incidentally
            fill in any missing Content-Disposition / Last-Modified)."""
            result: dict = {"total": 0}
            try:
                with session.stream(url) as resp:
                    resp.raise_for_status()
                    cl = resp.headers.get("Content-Length")
                    cr = resp.headers.get("Content-Range")
                    if cr is not None:
                        try:
                            result["total"] = int(cr.rsplit("/", 1)[-1])
                        except (ValueError, IndexError):
                            pass
                    if result["total"] <= 0 and cl is not None:
                        result["total"] = int(cl)
                    cd = _parse_content_disposition(
                        resp.headers.get("Content-Disposition", "")
                    )
                    if cd:
                        result["cd_filename"] = cd
                    lm = resp.headers.get("Last-Modified")
                    if lm:
                        result["last_modified"] = lm
            except Exception:
                pass
            return result

        def _range_probe():
            """Phase 3: tiny Range GET to fill in Content-Disposition /
            Last-Modified when HEAD did not provide them."""
            result: dict = {}
            try:
                with session.stream(
                    url, headers={"Range": "bytes=0-0"},
                ) as probe:
                    probe.raise_for_status()
                    cd = _parse_content_disposition(
                        probe.headers.get("Content-Disposition", "")
                    )
                    if cd:
                        result["cd_filename"] = cd
                    lm = probe.headers.get("Last-Modified")
                    if lm:
                        result["last_modified"] = lm
            except Exception:
                pass
            return result

        # ------------------------------------------------------------------
        # Execute follow-up probes — in parallel when both are needed
        # ------------------------------------------------------------------
        if need_stream_get and need_range:
            # Phase 2 ‖ Phase 3 — saves one sequential round-trip
            with ThreadPoolExecutor(max_workers=2) as executor:
                stream_fut = executor.submit(_stream_get_probe)
                range_fut = executor.submit(_range_probe)
                stream_result = stream_fut.result()
                range_result = range_fut.result()

            if stream_result["total"] > 0:
                total = stream_result["total"]
            if cd_filename is None:
                cd_filename = (
                    stream_result.get("cd_filename")
                    or range_result.get("cd_filename")
                )
            if last_modified is None:
                last_modified = (
                    stream_result.get("last_modified")
                    or range_result.get("last_modified")
                )

        elif need_stream_get:
            # Phase 2 only
            stream_result = _stream_get_probe()
            if stream_result["total"] > 0:
                total = stream_result["total"]
            if cd_filename is None:
                cd_filename = stream_result.get("cd_filename")
            if last_modified is None:
                last_modified = stream_result.get("last_modified")

        elif need_range:
            # Phase 3 only
            range_result = _range_probe()
            if cd_filename is None:
                cd_filename = range_result.get("cd_filename")
            if last_modified is None:
                last_modified = range_result.get("last_modified")

        if total <= 0:
            logger.warning(
                "Server did not provide Content-Length; "
                "falling back to single-threaded download"
            )

        return _Metadata(
            total=total,
            cd_filename=cd_filename,
            last_modified=last_modified,
        )

    # ------------------------------------------------------------------
    # Pre- / post-download helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_already_downloaded(
        *,
        dest: Path,
        total: int,
        expected_size: int | None,
        expected_hash: str | None,
        part_path: Path,
        partial_size: int,
        start_time: float,
    ) -> None:
        """Raise :class:`_AlreadyDownloaded` if *dest* already exists and is complete.

        Parameters
        ----------
        dest : Path
            Final destination path.
        total : int
            Expected file size.  If <= 0 the check is skipped.
        expected_size : int or None
            Expected file size for integrity verification.
        expected_hash : str or None
            Expected hash (``"algo:hexdigest"``) for integrity verification.
        part_path : Path
            Path to the ``.part`` file (cleaned up if present).
        partial_size : int
            Current size of the partial file.
        start_time : float
            ``time.monotonic()`` timestamp from the start of the download
            call (used for elapsed-time in the sentinel).
        """
        if total <= 0:
            return
        if dest.is_file() and dest.stat().st_size == total:
            if FileManager.check_integrity(
                dest,
                expected_size=expected_size,
                expected_hash=expected_hash,
            ):
                if partial_size > 0 and part_path.is_file():
                    part_path.unlink()
                elapsed = time.monotonic() - start_time
                raise _AlreadyDownloaded(total, elapsed, dest)

    @staticmethod
    def _check_partial_complete(
        part_path: Path,
        dest: Path,
        partial_size: int,
        total: int,
    ) -> tuple[int, Path] | None:
        """Return ``(total, dest)`` if the partial file is already complete.

        When the partial file already covers the entire remote file,
        rename it to the final destination and return the result tuple.
        Otherwise return ``None`` to indicate that downloading should
        proceed.
        """
        if total > 0 and partial_size >= total:
            os.replace(part_path, dest)
            return total, dest
        return None

    @staticmethod
    def _calculate_chunks(
        total: int, workers: int,
    ) -> list[tuple[int, int, int]]:
        """Compute byte-range boundaries for parallel download.

        Returns a list of ``(idx, start_byte, end_byte_inclusive)`` tuples
        that cover the range ``[0, total)`` without gaps.
        """
        num_chunks = max(workers * 4, 8)
        actual_chunk_size = max(
            1024 * 1024, (total + num_chunks - 1) // num_chunks,
        )
        num_chunks = (total + actual_chunk_size - 1) // actual_chunk_size
        num_chunks = min(num_chunks, workers * 8)

        chunks: list[tuple[int, int, int]] = []
        for i in range(num_chunks):
            start = i * actual_chunk_size
            end = min(start + actual_chunk_size, total) - 1
            if start < total:
                chunks.append((i, start, end))
        return chunks

    @staticmethod
    def _finalize_download(
        part_path: Path,
        dest: Path,
        last_modified: str | None,
    ) -> Path:
        """Rename ``.part`` → *dest* and apply ``Last-Modified`` timestamp.

        Returns *dest* so callers can chain or inspect the final path.
        """
        os.replace(part_path, dest)
        _apply_last_modified(dest, last_modified)
        return dest

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
        metadata: _Metadata,
        start_time: float = 0,
    ) -> tuple[int, Path]:
        """Stream download into *part_path*, then rename to *dest*.

        Returns ``(bytes_downloaded, final_dest_path)``.
        """
        headers: dict[str, str] = {}
        if partial_size > 0:
            headers["Range"] = f"bytes={partial_size}-"

        mode = "ab" if partial_size > 0 else "wb"
        downloaded = partial_size

        with session.stream(url, headers=headers) as resp:
            if resp.status_code == 404:
                raise RuntimeError("HTTP 404 Not Found")
            resp.raise_for_status()

            # Resolve total from response (stream may have per-response headers
            # that differ from the pre-flight metadata probe).
            total = metadata.total
            if total <= 0:
                cr = resp.headers.get("Content-Range")
                if cr is not None:
                    try:
                        total = int(cr.rsplit("/", 1)[-1])
                    except (ValueError, IndexError):
                        pass
                if total <= 0:
                    cl = resp.headers.get("Content-Length")
                    if cl is not None:
                        total = int(cl)

            # Capture filename from this response (TNG HEAD often omits
            # Content-Disposition, so the pre-flight metadata probe may have
            # missed it).  Three scenarios are handled here:
            #   1. Real-name file exists & complete → fix mtime, skip
            #   2. Real-name file exists, mtime wrong   → fix mtime, skip
            #   3. URL-name file exists, real-name doesn't → rename + fix mtime, skip
            cd_filename = _parse_content_disposition(
                resp.headers.get("Content-Disposition", "")
            )
            resp_last_modified = resp.headers.get("Last-Modified")
            if cd_filename:
                real_dest = dest.parent / cd_filename

                # Scenario 1 & 2: real-name file already exists and is complete
                if total > 0 and real_dest.is_file() and real_dest.stat().st_size == total:
                    _apply_last_modified(
                        real_dest,
                        resp_last_modified or metadata.last_modified,
                    )
                    if part_path.is_file():
                        part_path.unlink()
                    elapsed = time.monotonic() - start_time if start_time else 0
                    raise _AlreadyDownloaded(total, elapsed, real_dest)

                # Scenario 3: URL-derived name exists, real name doesn't.
                # Rename the local file instead of re-downloading.
                if real_dest != dest:
                    if total > 0 and dest.is_file() and dest.stat().st_size == total:
                        os.replace(dest, real_dest)
                        _apply_last_modified(
                            real_dest,
                            resp_last_modified or metadata.last_modified,
                        )
                        if part_path.is_file():
                            part_path.unlink()
                        elapsed = time.monotonic() - start_time if start_time else 0
                        raise _AlreadyDownloaded(total, elapsed, real_dest)

                dest = real_dest

            # Stream body to disk
            with open(part_path, mode) as fh:
                for chunk in resp.iter_bytes(chunk_size=chunk_size):
                    if limiter is not None:
                        wait = limiter.acquire(len(chunk))
                        if wait > 0:
                            time.sleep(wait)

                    fh.write(chunk)
                    downloaded += len(chunk)

                    if progress is not None:
                        effective_total = total if total > 0 else downloaded
                        progress(downloaded, effective_total)

        # Preserve Last-Modified from the actual download response when
        # available (it takes precedence over the metadata probe).
        last_modified: str | None = None
        if hasattr(resp, 'headers'):
            last_modified = (
                resp.headers.get("Last-Modified") or metadata.last_modified
            )
        else:
            last_modified = metadata.last_modified

        self._finalize_download(part_path, dest, last_modified)
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
        metadata: _Metadata,
    ) -> tuple[int, Path]:
        """Parallel chunk download: each chunk is written directly to the
        correct byte offset via :func:`os.pwrite`, avoiding an in-memory
        assembly buffer.

        Returns ``(bytes_downloaded, final_dest_path)``.
        """
        total = metadata.total

        # -- Sanity-check partial data --------------------------------------
        if partial_size >= total:
            if _is_sparse_file(part_path):
                logger.warning(
                    "Existing .part file is sparse (interrupted pre-allocation); "
                    "restarting download."
                )
                part_path.unlink()
            else:
                self._finalize_download(part_path, dest, metadata.last_modified)
                return total, dest

        # -- Calculate chunk boundaries -------------------------------------
        chunks = self._calculate_chunks(total, workers)

        # -- Pre-allocate the .part file (sparse on most filesystems) --------
        logger.info(
            "Pre-allocating %.1f GiB for multi-threaded download (%d chunks × %d workers).",
            total / (1024 ** 3), len(chunks), workers,
        )
        with open(part_path, "w+b") as fh:
            fh.truncate(total)

            # -- Download chunks in parallel, writing as they arrive ---------
            downloaded = 0
            _dl_lock = threading.Lock()
            _stop_event = threading.Event()

            def _on_read(n: int) -> None:
                """Fine-grained progress: called by every worker after each read."""
                nonlocal downloaded
                with _dl_lock:
                    downloaded += n

            def _poll_progress() -> None:
                """Background thread: report progress at ~4 Hz so the
                progress bar stays responsive between chunk completions."""
                while not _stop_event.is_set():
                    _stop_event.wait(0.25)
                    if progress is not None:
                        with _dl_lock:
                            cur = downloaded
                        progress(cur, total)

            if progress is not None:
                _progress_thread = threading.Thread(
                    target=_poll_progress, daemon=True,
                )
                _progress_thread.start()

            try:
                with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
                    # Map each future to its (idx, start_byte) for pwrite
                    future_map: dict = {}
                    for idx, start, end in chunks:
                        fut = executor.submit(
                            _fetch_chunk,
                            session, url, chunk_size, idx, start, end, limiter, _on_read,
                        )
                        future_map[fut] = (idx, start)

                    for future in as_completed(future_map):
                        idx, data = future.result()
                        _, start = future_map[future]
                        os.pwrite(fh.fileno(), data, start)
                        # `downloaded` is already kept current by _on_read
                        # and the polling thread; fire one final update.
                        if progress is not None:
                            progress(downloaded, total)
            finally:
                _stop_event.set()
                if progress is not None:
                    progress(downloaded, total)  # final snapshot

        self._finalize_download(part_path, dest, metadata.last_modified)
        return downloaded, dest


class _AlreadyDownloaded(Exception):
    """Internal sentinel: file was already fully downloaded."""

    def __init__(self, size: int, elapsed: float, dest: Path) -> None:
        self.size = size
        self.elapsed = elapsed
        self.dest = dest
