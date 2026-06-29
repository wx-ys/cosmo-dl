"""Rich progress display for cosmo-dl downloads.

Provides two context-manager classes:

- :class:`SingleFileProgress` — one clean progress bar for a single file.
- :class:`MultiFileProgress` — Docker-pull-style display with file-level
  dots, per-active-file bars, and an aggregate total bar.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
)

_console = Console()


# Module-level progress hook for registry tree scraping.
# Set by ``api.download()`` before target resolution; cleared afterwards.
# ``fire._scrape_dir()`` checks this hook to report real-time progress.
_registry_resolve_hook: Callable[[int, int, str], None] | None = None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def fmt_speed(bytes_per_second: float) -> str:
    """Format a bytes-per-second rate as a human-readable string."""
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f} MB/s"
    elif bytes_per_second >= 1024:
        return f"{bytes_per_second / 1024:.0f} KB/s"
    elif bytes_per_second > 0:
        return f"{bytes_per_second:.0f} B/s"
    return ""


def fmt_bytes(size: int) -> str:
    """Format a byte count as a human-readable string."""
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024**3):.1f} GiB"
    elif size >= 1024 * 1024:
        return f"{size / (1024**2):.1f} MiB"
    elif size >= 1024:
        return f"{size / 1024:.0f} KiB"
    return f"{size} B"


# ---------------------------------------------------------------------------
# Shared column definitions
# ---------------------------------------------------------------------------


def _build_columns(text_format: str) -> tuple:
    """Return a standard progress-column tuple with *text_format* as the
    :class:`~rich.progress.TextColumn` format string."""
    return (
        SpinnerColumn(),
        TextColumn(text_format),
        BarColumn(bar_width=None, pulse_style="bar.back"),
        "[progress.percentage]{task.percentage:>3.0f}%",
        " • ",
        DownloadColumn(),
        " • ",
        TextColumn("{task.fields[speed_str]}"),
        " • ",
        TextColumn("{task.fields[eta_str]}"),
    )


_SINGLE_FILE_COLUMNS = _build_columns("[bold blue]{task.fields[filename]}")
_MULTI_FILE_COLUMNS = _build_columns("{task.description}")


# ---------------------------------------------------------------------------
# SingleFileProgress
# ---------------------------------------------------------------------------


class SingleFileProgress:
    """Rich progress bar for a single-file download.

    Usage::

        with SingleFileProgress("snap.hdf5") as sfp:
            downloader.download(url, dest, progress=sfp.callback)
    """

    def __init__(
        self,
        filename: str,
        *,
        worker_count: int = 1,
        console: Console | None = None,
    ) -> None:
        label = filename[:50]
        if worker_count > 1:
            label = f"{label} ({worker_count}w)"

        self.progress = Progress(
            *_SINGLE_FILE_COLUMNS,
            console=console or _console,
            expand=True,
        )
        self.task_id = self.progress.add_task(
            "download",
            filename=label,
            total=None,
            start=True,
            speed_str="?",
            eta_str="-:--:--",
        )
        self._start_time = time.monotonic()
        self._stop_poll = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def __enter__(self) -> SingleFileProgress:
        self.progress.start()
        self._poll_thread = threading.Thread(target=self._poll, daemon=True)
        self._poll_thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop_poll.set()
        self.progress.stop()

    def _poll(self) -> None:
        """Refresh speed / ETA at ~2 Hz."""
        while not self._stop_poll.is_set():
            self._stop_poll.wait(0.5)
            # _last_downloaded and _last_total are set by callback(); we just
            # recompute speed / ETA from the cached values so the display
            # stays responsive between downloader callbacks.
            now = time.monotonic()
            elapsed = now - self._start_time
            dl = getattr(self, "_last_downloaded", 0)
            tot = getattr(self, "_last_total", 0)

            if elapsed >= 0.5 and dl > 0:
                speed = dl / elapsed
                speed_str = f"[cyan]{fmt_speed(speed)}[/cyan]"
                if tot > 0 and speed > 0 and tot > dl:
                    remaining = (tot - dl) / speed
                    m, s = divmod(int(remaining), 60)
                    h, m = divmod(m, 60)
                    eta_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                else:
                    eta_str = "-:--:--"
            else:
                speed_str = "?"
                eta_str = "-:--:--"

            self.progress.update(
                self.task_id,
                completed=dl,
                total=tot or None,
                speed_str=speed_str,
                eta_str=eta_str,
            )

    def callback(self, downloaded: int, total: int) -> None:
        """Progress callback for ``Downloader.download(progress=...)``."""
        self._last_downloaded = downloaded
        self._last_total = total
        if total > 0:
            self.progress.update(self.task_id, total=total, completed=downloaded)
        else:
            self.progress.update(self.task_id, completed=downloaded, total=downloaded)


# ---------------------------------------------------------------------------
# MultiFileProgress
# ---------------------------------------------------------------------------


@dataclass
class _FileState:
    """Per-file tracking for :class:`MultiFileProgress`."""

    status: str = "pending"  # pending | active | done | failed
    task_id: TaskID | None = None
    last: int = 0  # last reported downloaded bytes (for delta computation)
    # Per-file speed / ETA tracking
    start_time: float = 0.0  # monotonic timestamp of first byte
    total_size: int | None = None  # expected file size (from HEAD or callback)


class MultiFileProgress:
    """Docker-pull-style multi-file progress display.

    Two visual layers in one :class:`~rich.progress.Progress` widget:

    * **Aggregate bar** (top) — file count + total bytes across all files.
    * **Per-file bars** — one per actively downloading file.

    Completed / failed files are hidden (``visible=False``) to keep the
    display compact.

    Usage::

        display = MultiFileProgress()
        for f in files:
            display.add_pending(f.name)
        with display:
            for f in files:
                cb = display.start_file(f.name, total_size=f.size)
                result = downloader.download(f.url, f.dest, progress=cb)
                display.complete_file(f.name, success=result.success)
    """

    def __init__(
        self,
        *,
        total_bytes: int = 0,
        total_known: bool = False,
        console: Console | None = None,
        refresh_interval: float = 0.5,
    ) -> None:
        self.console = console or _console
        self._files: dict[str, _FileState] = {}
        self._file_order: list[str] = []
        self._shared_downloaded = 0
        self._lock = threading.Lock()

        # Counters so _render_aggregate is O(1), not O(n)
        self._n_done = 0
        self._n_failed = 0
        self._n_active = 0

        # Refresh interval for per-file speed / ETA polling (seconds)
        self._refresh_interval = refresh_interval

        self.progress = Progress(
            *_MULTI_FILE_COLUMNS,
            console=self.console,
            expand=True,
        )

        # -- Aggregate task (top row) ----------------------------------------
        self._aggregate_task = self.progress.add_task(
            "",  # description set by _render_aggregate
            total=total_bytes if (total_known and total_bytes > 0) else None,
            start=True,
            speed_str="?",
            eta_str="-:--:--",
        )
        self._agg_total: int | None = total_bytes if (total_known and total_bytes > 0) else None

        # -- Polling thread keeps aggregated speed/ETA responsive ------------
        self._stop_poll = threading.Event()
        self._poll_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> MultiFileProgress:
        self.progress.start()
        self._poll_thread = threading.Thread(target=self._poll, daemon=True)
        self._poll_thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop_poll.set()
        self.progress.stop()

    def _poll(self) -> None:
        """Refresh aggregate and per-file speed / ETA at ``refresh_interval`` Hz.

        Unlike rich's built-in :class:`~rich.progress.TransferSpeedColumn` and
        :class:`~rich.progress.TimeRemainingColumn` — which require multiple
        progress samples separated in time — this method computes speed and
        ETA directly from elapsed wall-clock time and pushes the results into
        each task's ``speed_str`` / ``eta_str`` fields.  This works reliably
        even for small files that receive only one or two progress callbacks.
        """
        # Per-poll tracking for the aggregate bar's speed / ETA
        _agg_last_bytes = 0
        _agg_last_time = time.monotonic()
        _agg_speed = 0.0

        while not self._stop_poll.is_set():
            self._stop_poll.wait(self._refresh_interval)
            now = time.monotonic()

            # -- Aggregate bar -------------------------------------------------
            with self._lock:
                cur = self._shared_downloaded

            elapsed = now - _agg_last_time
            if elapsed >= self._refresh_interval * 0.8:
                delta = cur - _agg_last_bytes
                if delta > 0 and elapsed > 0:
                    _agg_speed = delta / elapsed
                _agg_last_bytes = cur
                _agg_last_time = now

            agg_total = self._agg_total
            agg_speed_str = f"[cyan]{fmt_speed(_agg_speed)}[/cyan]" if _agg_speed > 0 else "?"
            if _agg_speed > 0 and agg_total is not None and agg_total > 0:
                remaining = (agg_total - cur) / _agg_speed
                m, s = divmod(int(remaining), 60)
                h, m = divmod(m, 60)
                agg_eta_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            else:
                agg_eta_str = "-:--:--"

            self.progress.update(
                self._aggregate_task,
                completed=cur,
                speed_str=agg_speed_str,
                eta_str=agg_eta_str,
            )

            # -- Per-file bars ------------------------------------------------
            for _key, state in list(self._files.items()):
                if state.status != "active" or state.task_id is None:
                    continue

                elapsed_file = now - state.start_time
                if elapsed_file >= 0.5 and state.last > 0:
                    file_speed = state.last / elapsed_file
                    file_speed_str = (
                        f"[cyan]{fmt_speed(file_speed)}[/cyan]" if file_speed > 0 else "?"
                    )
                    if file_speed > 0 and state.total_size and state.total_size > state.last:
                        remaining_f = (state.total_size - state.last) / file_speed
                        mf, sf = divmod(int(remaining_f), 60)
                        hf, mf = divmod(mf, 60)
                        file_eta_str = f"{hf}:{mf:02d}:{sf:02d}" if hf else f"{mf:02d}:{sf:02d}"
                    else:
                        file_eta_str = "-:--:--"
                else:
                    file_speed_str = "?"
                    file_eta_str = "-:--:--"

                self.progress.update(
                    state.task_id,
                    completed=state.last,
                    total=state.total_size,
                    speed_str=file_speed_str,
                    eta_str=file_eta_str,
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_pending(self, key: str) -> None:
        """Register a file that will be downloaded (shows as ◌ in dots)."""
        if key not in self._files:
            self._files[key] = _FileState(status="pending")
            self._file_order.append(key)
        self._render_aggregate()

    def start_file(self, key: str, total_size: int | None = None) -> Callable[[int, int], None]:
        """Mark *key* as downloading, add its progress bar, return a callback.

        The returned callback is compatible with
        ``Downloader.download(progress=...)``.
        """
        state = self._files.get(key) or _FileState()
        if state.status != "active":
            if state.status == "pending":
                self._n_active += 1
            state.status = "active"
        state.last = 0
        state.start_time = time.monotonic()
        state.total_size = total_size
        self._files[key] = state

        # Add a per-file task row.  Speed / ETA are empty initially;
        # _poll fills them in once there is data.
        task_id = self.progress.add_task(
            f"  {key[:48]}",
            total=total_size,
            start=True,
            speed_str="",
            eta_str="",
        )
        state.task_id = task_id

        self._render_aggregate()

        return self._make_callback(key)

    def enqueue_file(self, key: str, total_size: int | None = None) -> Callable[[int, int], None]:
        """Register *key* as **queued** and return a deferred callback.

        Unlike :meth:`start_file`, this does **not** create a progress bar
        or count the file as active.  The returned callback automatically
        promotes the file to ``"active"`` and creates its progress bar on
        the first invocation (i.e. when the download actually begins).

        Use this when submitting many files to a :class:`ThreadPoolExecutor`
        — only files whose downloads have started get visible progress bars.
        """
        state = self._files.get(key)
        if state is None:
            state = _FileState(status="pending")
            self._files[key] = state
        state.status = "queued"
        self._render_aggregate()
        return self._make_deferred_callback(key, total_size)

    # ------------------------------------------------------------------
    # Callback factories
    # ------------------------------------------------------------------

    def _make_callback(self, key: str) -> Callable[[int, int], None]:
        """Return a callback that updates the per-file bar + aggregate."""
        file_key = key

        def cb(downloaded: int, total: int) -> None:
            st = self._files.get(file_key)
            if st is None:
                return
            # Update total from the downloader's response (may be more
            # accurate than the HEAD pre-fetch, or set for the first time
            # when HEAD returned no Content-Length).
            if total > 0 and st.total_size != total:
                old_size = st.total_size or 0
                st.total_size = total
                # Update the aggregate total so the overall progress bar
                # shows a meaningful total even when some HEAD pre-fetches
                # failed.  The aggregate grows by the delta between the
                # real size and whatever we knew before (often 0).
                if self._agg_total is not None or old_size != total:
                    self._agg_total = (self._agg_total or 0) + (total - old_size)
                    self.progress.update(
                        self._aggregate_task,
                        total=self._agg_total,
                    )
            tid = st.task_id
            if tid is not None:
                if total > 0:
                    self.progress.update(tid, total=total, completed=downloaded)
                else:
                    self.progress.update(tid, completed=downloaded, total=downloaded)
            delta = downloaded - st.last
            st.last = downloaded
            with self._lock:
                self._shared_downloaded += delta
                cur = self._shared_downloaded
            # Nudge aggregate bar on every chunk so speed/ETA stay fresh
            # between _poll cycles.
            self.progress.update(self._aggregate_task, completed=cur)

        return cb

    def _make_deferred_callback(
        self, key: str, total_size: int | None
    ) -> Callable[[int, int], None]:
        """Return a callback that auto-activates the file on first call.

        On the first invocation the file transitions ``"queued" → "active"``
        and its per-file progress bar is created.  Subsequent calls behave
        identically to the callback returned by :meth:`_make_callback`.
        """
        file_key = key
        _activated = False

        def cb(downloaded: int, total: int) -> None:
            nonlocal _activated
            st = self._files.get(file_key)
            if st is None:
                return

            if not _activated and st.status == "queued":
                _activated = True
                st.status = "active"
                self._n_active += 1
                task_id = self.progress.add_task(
                    f"  {file_key[:48]}",
                    total=total_size,
                    start=True,
                )
                st.task_id = task_id
                self._render_aggregate()

            # Update total from the downloader's response.  When the HEAD
            # pre-fetch didn't provide a size, this is the first time we
            # learn it — update the aggregate total accordingly.
            if total > 0 and st.total_size != total:
                old_size = st.total_size or 0
                st.total_size = total
                if self._agg_total is not None or old_size != total:
                    self._agg_total = (self._agg_total or 0) + (total - old_size)
                    self.progress.update(
                        self._aggregate_task,
                        total=self._agg_total,
                    )

            tid = st.task_id
            if tid is not None:
                if total > 0:
                    self.progress.update(tid, total=total, completed=downloaded)
                else:
                    self.progress.update(tid, completed=downloaded, total=downloaded)
            delta = downloaded - st.last
            st.last = downloaded
            with self._lock:
                self._shared_downloaded += delta
                cur = self._shared_downloaded
            self.progress.update(self._aggregate_task, completed=cur)

        return cb

    def complete_file(self, key: str, *, success: bool = True, actual_size: int = 0) -> None:
        """Mark a file as done or failed and hide its progress bar.

        Parameters
        ----------
        key : str
            File key (typically the filename).
        success : bool
            ``True`` for a successful download, ``False`` for a failure.
        actual_size : int
            Actual bytes downloaded.  Provide this for already-downloaded
            files whose progress callback never fired (the downloader raises
            an internal sentinel before the first callback invocation).
        """
        state = self._files.get(key)
        if state is None:
            return
        was_active = state.status == "active"
        state.status = "done" if success else "failed"
        if was_active:
            self._n_active -= 1
        if success:
            self._n_done += 1
        else:
            self._n_failed += 1
        if state.task_id is not None:
            self.progress.update(state.task_id, visible=False)
        if actual_size > 0:
            with self._lock:
                self._shared_downloaded += actual_size
        self._render_aggregate()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _render_aggregate(self) -> None:
        """Build the file-count summary and push it to the aggregate task."""
        n_total = len(self._files)
        parts = [f"{self._n_done}/{n_total} files"]
        if self._n_active:
            parts.append(f" • {self._n_active} active")
        if self._n_failed:
            parts.append(f" • {self._n_failed} failed")
        self.progress.update(self._aggregate_task, description="".join(parts))
