"""Tests for engine package exports."""
from cosmo_dl.engine import (
    Downloader,
    URLExplorer,
    FileManager,
    Session,
    RateLimiter,
    DownloadResult,
    FileEntry,
    AuthConfig,
    MB,
)


def test_all_exports_available():
    """Verify all public engine symbols are importable from cosmo_dl.engine."""
    assert Downloader is not None
    assert URLExplorer is not None
    assert FileManager is not None
    assert Session is not None
    assert RateLimiter is not None
    assert DownloadResult is not None
    assert FileEntry is not None
    assert AuthConfig is not None
    assert MB == 1_048_576
