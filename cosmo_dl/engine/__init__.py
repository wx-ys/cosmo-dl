"""Engine layer: core download capabilities with zero astronomy dependency."""
from cosmo_dl.engine.downloader import MB, Downloader
from cosmo_dl.engine.explorer import URLExplorer
from cosmo_dl.engine.file_manager import FileManager
from cosmo_dl.engine.rate_limiter import RateLimiter
from cosmo_dl.engine.session import Session
from cosmo_dl.engine.types import AuthConfig, DownloadResult, FileEntry

__all__ = [
    "Downloader",
    "URLExplorer",
    "FileManager",
    "Session",
    "RateLimiter",
    "DownloadResult",
    "FileEntry",
    "AuthConfig",
    "MB",
]
