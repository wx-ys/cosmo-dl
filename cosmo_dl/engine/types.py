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
    checksum: str | None = None


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
    """Authentication configuration for HTTP sessions.

    Supported ``type`` values:

    * ``"none"`` — no authentication
    * ``"basic"`` — HTTP Basic Auth (``username`` + ``password``)
    * ``"bearer"`` — static ``Authorization: Bearer <token>`` header
    * ``"api-key"`` — ``api-key: <token>`` header (e.g. IllustrisTNG)
    * ``"cookie"`` — Mozilla cookie file
    * ``"oauth2"`` — OAuth2 with automatic token refresh (e.g. Globus)

    When ``type`` is ``"oauth2"``, the Session will automatically refresh
    the access token before it expires using the stored refresh token.
    Tokens are persisted to ``~/.config/cosmo-dl/tokens.json``.
    """

    type: Literal["none", "basic", "bearer", "cookie", "api-key", "oauth2"] = "none"
    username: str | None = None
    password: str | None = None
    token: str | None = None
    cookie_file: str | None = None
    custom_headers: dict[str, str] = field(default_factory=dict)

    # -- OAuth2 fields -------------------------------------------------------
    client_id: str | None = None
    client_secret: str | None = None
    token_url: str | None = None
    authorize_url: str | None = None
    scopes: str | None = None
    redirect_uri: str | None = None
    # Transient token state (loaded from tokens.json at session creation)
    refresh_token: str | None = None
    access_token: str | None = None
    token_expiry: float | None = None
    # Unique identifier for this auth config (used as key in tokens.json)
    source_name: str | None = None
