"""Core types for the cosmo-dl engine."""
from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class DownloadResult:
    """Result of a single file download."""
    url: str
    local_path: str
    size: int
    elapsed: float
    speed: float
    success: bool
    message: str = "OK"


@dataclass(slots=True)
class FileEntry:
    """Represents a file or directory discovered at a URL."""
    url: str
    name: str
    size: int | None = None
    type: Literal["file", "dir"] = "file"
    modified: str | None = None


@dataclass(slots=True)
class AuthConfig:
    """Authentication configuration for HTTP sessions."""
    type: Literal["none", "basic", "bearer", "cookie"] = "none"
    username: str | None = None
    password: str | None = None
    token: str | None = None
    cookie_file: str | None = None
    custom_headers: dict[str, str] = field(default_factory=dict)
