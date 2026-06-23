"""Rich progress display for cosmo-dl downloads.

Provides two context-manager classes:

- :class:`SingleFileProgress` — one clean progress bar for a single file.
- :class:`MultiFileProgress` — Docker-pull-style display with file-level
  dots, per-active-file bars, and an aggregate total bar.
"""

from __future__ import annotations

import threading
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
    TimeRemainingColumn,
    TransferSpeedColumn,
)

_console = Console()

# ---------------------------------------------------------------------------
# Shared column definitions
# ---------------------------------------------------------------------------

_SINGLE_FILE_COLUMNS = (
    SpinnerColumn(),
    TextColumn("[bold blue]{task.fields[filename]}"),
    BarColumn(bar_width=None, pulse_style="bar.back"),
    "[progress.percentage]{task.percentage:>3.0f}%",
    " • ",
    DownloadColumn(),
    " • ",
    TransferSpeedColumn(),
    " • ",
    TimeRemainingColumn(),
)

_MULTI_FILE_COLUMNS = (
    SpinnerColumn(),
    TextColumn("{task.description}"),
    BarColumn(bar_width=None, pulse_style="bar.back"),
    "[progress.percentage]{task.percentage:>3.0f}%",
    " • ",
    DownloadColumn(),
    " • ",
    TransferSpeedColumn(),
    " • ",
    TimeRemainingColumn(),
)


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
        )

    def __enter__(self) -> SingleFileProgress:
        self.progress.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.progress.stop()

    def callback(self, downloaded: int, total: int) -> None:
        """Progress callback for ``Downloader.download(progress=...)``."""
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
    ) -> None:
        self.console = console or _console
        self._files: dict[str, _FileState] = {}
        self._file_order: list[str] = []
        self._shared_downloaded = 0
        self._lock = threading.Lock()

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
        )

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
        """Nudge the aggregate bar at ~2 Hz so speed / ETA stay fresh."""
        while not self._stop_poll.is_set():
            self._stop_poll.wait(0.5)
            with self._lock:
                cur = self._shared_downloaded
            self.progress.update(self._aggregate_task, completed=cur)

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
        state.status = "active"
        state.last = 0
        self._files[key] = state

        # Add a per-file task row
        task_id = self.progress.add_task(
            f"  {key[:48]}",
            total=total_size,
            start=True,
        )
        state.task_id = task_id

        self._render_aggregate()

        # -- Build closure that updates both the per-file bar and aggregate --
        file_key = key

        def cb(downloaded: int, total: int) -> None:
            st = self._files.get(file_key)
            if st is None:
                return
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
            # Nudge aggregate bar on every chunk so TransferSpeedColumn
            # and TimeRemainingColumn get frequent data points.
            self.progress.update(self._aggregate_task, completed=cur)

        return cb

    def complete_file(self, key: str, *, success: bool = True) -> None:
        """Mark a file as done (●) or failed (✗) and hide its progress bar."""
        state = self._files.get(key)
        if state is None:
            return
        state.status = "done" if success else "failed"
        if state.task_id is not None:
            self.progress.update(state.task_id, visible=False)
        self._render_aggregate()

    def complete_file_with_size(
        self,
        key: str,
        *,
        success: bool = True,
        actual_size: int = 0,
    ) -> None:
        """Like :meth:`complete_file` but also credits *actual_size* to the
        aggregate counter.

        Use for already-downloaded files whose callback never fired.
        """
        if actual_size > 0:
            with self._lock:
                self._shared_downloaded += actual_size
        self.complete_file(key, success=success)

    def set_aggregate_total(self, total: int) -> None:
        """Set the aggregate total (from HEAD pre-fetch)."""
        self.progress.update(self._aggregate_task, total=total)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _render_aggregate(self) -> None:
        """Build the file-count summary and push it to the aggregate task."""
        n_total = len(self._files)
        n_done = sum(1 for s in self._files.values() if s.status == "done")
        n_failed = sum(1 for s in self._files.values() if s.status == "failed")
        n_active = sum(1 for s in self._files.values() if s.status == "active")

        parts = [f"{n_done}/{n_total} files"]
        if n_active:
            parts.append(f" • {n_active} active")
        if n_failed:
            parts.append(f" • {n_failed} failed")

        self.progress.update(
            self._aggregate_task,
            description="".join(parts),
        )
