"""Core download engine with resume, multi-threading, rate limiting, and integrity."""
from __future__ import annotations

import os
import re
import time
import shutil
import email.utils
from dataclasses import dataclass
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
                elif dest.is_file() and dest.stat().st_size > 0:
                    shutil.copy2(dest, part_path)
                    partial_size = dest.stat().st_size

            # -- Gather remote metadata ---------------------------------------
            # Single-threaded: HEAD only (the stream GET response is needed by
            # _download_single — we must not consume it here).
            # Multi-threaded: full probing (HEAD → stream GET → Range probe)
            # so we know the total size for chunk partitioning.
            metadata = self._gather_metadata(
                session, url, fallback_get=(workers > 1),
            )

            # Apply server-provided filename from Content-Disposition
            if metadata.cd_filename:
                dest = dest.parent / metadata.cd_filename

            # -- Pre-download checks ------------------------------------------
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
            elif workers <= 1:
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
        only when necessary.

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

        # Phase 2: stream GET fallback when HEAD didn't give us a size
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
                if cd_filename is None:
                    cd_filename = _parse_content_disposition(
                        resp.headers.get("Content-Disposition", "")
                    )
                if last_modified is None:
                    last_modified = resp.headers.get("Last-Modified")
            if total <= 0:
                raise RuntimeError(
                    "Cannot perform multi-threaded download: "
                    "server did not provide Content-Length"
                )

        # Phase 3: tiny Range GET probe for any remaining missing metadata
        if total > 0 and (cd_filename is None or last_modified is None):
            try:
                with session.stream(
                    url, headers={"Range": "bytes=0-0"},
                ) as probe:
                    probe.raise_for_status()
                    if cd_filename is None:
                        cd_filename = _parse_content_disposition(
                            probe.headers.get("Content-Disposition", "")
                        )
                    if last_modified is None:
                        last_modified = probe.headers.get("Last-Modified")
            except Exception:
                pass

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

            # Capture filename from this response (in case it differs from probe)
            cd_filename = _parse_content_disposition(
                resp.headers.get("Content-Disposition", "")
            )
            if cd_filename:
                dest = dest.parent / cd_filename

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
        """Parallel chunk downloads assembled into *part_path*, then renamed to *dest*.

        Returns ``(bytes_downloaded, final_dest_path)``.
        """
        total = metadata.total

        # -- Sanity-check partial data --------------------------------------
        if partial_size >= total:
            self._finalize_download(part_path, dest, metadata.last_modified)
            return total, dest

        # -- Calculate chunk boundaries -------------------------------------
        chunks = self._calculate_chunks(total, workers)

        # -- Download chunks in parallel ------------------------------------
        chunk_data: dict[int, bytes] = {}
        downloaded = partial_size

        with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
            futures = [
                executor.submit(
                    _fetch_chunk,
                    session, url, chunk_size, idx, start, end, limiter,
                )
                for idx, start, end in chunks
            ]
            for future in as_completed(futures):
                idx, data = future.result()
                chunk_data[idx] = data
                downloaded += len(data)

                if progress is not None:
                    progress(downloaded, total)

        # -- Assemble chunks in order into .part file -----------------------
        with open(part_path, "wb") as fh:
            for i in range(len(chunks)):
                fh.write(chunk_data[i])

        self._finalize_download(part_path, dest, metadata.last_modified)
        return downloaded, dest


class _AlreadyDownloaded(Exception):
    """Internal sentinel: file was already fully downloaded."""

    def __init__(self, size: int, elapsed: float, dest: Path) -> None:
        self.size = size
        self.elapsed = elapsed
        self.dest = dest
