"""HTTP session manager wrapping requests.Session with auth, retry, and proxy support."""

from __future__ import annotations

import contextlib
import http.cookiejar
import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cosmo_dl.engine.types import AuthConfig

logger = logging.getLogger(__name__)


class _CrossOriginSession(requests.Session):
    """A :class:`requests.Session` that strips the ``api-key`` header on
    cross-origin redirects.

    The TNG data server rejects requests that carry both an ``api-key``
    header and a ``?token=...`` query parameter.  Since ``requests``
    normally preserves custom headers across redirects, the ``api-key``
    set for API authentication would leak to the data server and cause
    403 Forbidden errors.
    """

    def rebuild_auth(self, prepared_request, response):
        # Standard cross-origin auth stripping
        headers = prepared_request.headers
        url = prepared_request.url

        if "Authorization" in headers:
            original = urlparse(response.request.url)
            redirect = urlparse(url)
            if original.hostname != redirect.hostname:
                del headers["Authorization"]

        # Also strip api-key so it does not leak to data servers that
        # already authenticate via ?token=... query parameters.
        if response is not None and response.request and response.request.url:
            original = urlparse(response.request.url)
            redirect = urlparse(url)
            if original.hostname != redirect.hostname:
                headers.pop("api-key", None)


class StreamResponse:
    """Thin wrapper around a requests streaming response to expose a
    ``.headers`` dict (case-insensitive) and an ``iter_bytes()``
    iterator compatible with the old httpx-based downloader.
    """

    def __init__(self, response: requests.Response) -> None:
        self._response = response

    @property
    def headers(self) -> requests.structures.CaseInsensitiveDict:
        return self._response.headers

    @property
    def status_code(self) -> int:
        return self._response.status_code

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_bytes(self, chunk_size: int = 1024 * 1024):
        """Yield raw bytes from the response body."""
        return self._response.iter_content(chunk_size=chunk_size)

    def close(self) -> None:
        self._response.close()

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class Session:
    """Manages an HTTP session with configurable auth, retries, and proxy.

    Parameters
    ----------
    auth : AuthConfig or None
        Authentication configuration.
    headers : dict or None
        Additional HTTP headers for every request.
    cookies : dict or None
        Cookies to include in every request.
    retry : int
        Number of retries for failed requests (default 5).
    retry_backoff : float
        Backoff factor for retries (default 1.0).
    timeout : int
        Connect timeout in seconds (default 10).
    read_timeout : int
        Read timeout in seconds (default 300, suitable for large files).
    proxy : str or None
        Proxy URL (e.g. "http://proxy:8080").
    """

    def __init__(
        self,
        auth: AuthConfig | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        retry: int = 5,
        retry_backoff: float = 1.0,
        timeout: int = 10,
        read_timeout: int = 300,
        proxy: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.read_timeout = read_timeout
        self.retry = retry
        self.retry_backoff = retry_backoff
        self._timeout = (timeout, read_timeout)
        self._closed = False
        self._oauth2_auth: AuthConfig | None = None

        # Build extra headers from auth config
        extra_headers: dict[str, str] = {}
        extra_cookies: dict[str, str] | http.cookiejar.CookieJar | None = None

        if auth is not None:
            if auth.custom_headers:
                extra_headers.update(auth.custom_headers)

            if auth.type == "basic" and auth.username is not None and auth.password is not None:
                # requests handles BasicAuth via the session's .auth attribute
                self._requests_auth: requests.auth.AuthBase | None = requests.auth.HTTPBasicAuth(
                    auth.username, auth.password
                )
            else:
                self._requests_auth = None

            if auth.type == "bearer" and auth.token is not None:
                extra_headers["Authorization"] = f"Bearer {auth.token}"
            elif auth.type == "api-key" and auth.token is not None:
                extra_headers["api-key"] = auth.token
            elif auth.type == "cookie" and auth.cookie_file is not None:
                cj = http.cookiejar.MozillaCookieJar()
                with contextlib.suppress(FileNotFoundError):
                    cj.load(auth.cookie_file, ignore_discard=True, ignore_expires=True)
                extra_cookies = cj

            elif auth.type == "oauth2":
                # Load stored tokens and apply as Bearer
                self._oauth2_auth = auth
                self._load_oauth2_tokens()
                if auth.access_token:
                    extra_headers["Authorization"] = f"Bearer {auth.access_token}"
            else:
                self._oauth2_auth = None

        # Merge user-supplied headers with extra auth headers
        merged_headers: dict[str, str] = {}
        if extra_headers:
            merged_headers.update(extra_headers)
        if headers:
            merged_headers.update(headers)

        # Handle cookies
        merged_cookies: Any = None
        if extra_cookies is not None:
            merged_cookies = extra_cookies
        if cookies:
            merged_cookies = cookies

        # Build session with retry adapter.  _CrossOriginSession strips the
        # api-key header on cross-origin redirects so it does not leak to
        # data servers that authenticate via ?token=... query parameters.
        self._client = _CrossOriginSession()

        if merged_headers:
            self._client.headers.update(merged_headers)
        if merged_cookies is not None:
            if isinstance(merged_cookies, dict):
                self._client.cookies.update(merged_cookies)
            elif isinstance(merged_cookies, http.cookiejar.CookieJar):
                self._client.cookies = merged_cookies  # type: ignore[assignment]

        if hasattr(self, "_requests_auth") and self._requests_auth is not None:
            self._client.auth = self._requests_auth

        # Set up retry adapter
        retry_strategy = Retry(
            total=retry,
            backoff_factor=retry_backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=100,
            pool_maxsize=100,
        )
        self._client.mount("http://", adapter)
        self._client.mount("https://", adapter)

        # Proxy
        if proxy:
            self._client.proxies.update({"http": proxy, "https": proxy})

    @property
    def client(self) -> requests.Session:
        """Return the underlying requests.Session."""
        return self._client

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        """Send a HEAD request.

        Unlike :meth:`requests.Session.head`, redirects are followed by
        default so that ``Content-Length`` and other headers from the
        final destination are visible to callers.
        """
        self._ensure_fresh_token()
        kwargs.setdefault("timeout", self._timeout)
        kwargs.setdefault("allow_redirects", True)
        return self._client.head(url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Send a GET request."""
        self._ensure_fresh_token()
        kwargs.setdefault("timeout", self._timeout)
        return self._client.get(url, **kwargs)

    def stream(self, url: str, **kwargs: Any) -> contextlib.AbstractContextManager[StreamResponse]:
        """Send a GET request with streaming enabled.

        Returns a context manager yielding a :class:`StreamResponse` that
        provides ``headers``, ``status_code``, ``raise_for_status()``, and
        ``iter_bytes(chunk_size)`` — compatible with the old httpx-based API.
        """
        self._ensure_fresh_token()
        kwargs.setdefault("timeout", self._timeout)
        # Pop any 'method' kwarg (httpx compatibility)
        kwargs.pop("method", None)
        resp = self._client.get(url, stream=True, **kwargs)
        return StreamResponse(resp)

    # ------------------------------------------------------------------
    # OAuth2 token management
    # ------------------------------------------------------------------

    def _load_oauth2_tokens(self) -> None:
        """Load stored OAuth2 tokens for the configured source."""
        auth = self._oauth2_auth
        if auth is None or auth.source_name is None:
            return
        try:
            from cosmo_dl.config import get_token

            stored = get_token(auth.source_name)
            if stored:
                auth.refresh_token = str(stored.get("refresh_token", "")) or None
                auth.access_token = str(stored.get("access_token", "")) or None
                expiry = stored.get("token_expiry")
                auth.token_expiry = float(expiry) if expiry is not None else None  # type: ignore[arg-type]
        except Exception as exc:
            logger.debug("Failed to load OAuth2 tokens: %s", exc)

    def _persist_oauth2_tokens(self) -> None:
        """Save current OAuth2 tokens to persistent storage."""
        auth = self._oauth2_auth
        if auth is None or auth.source_name is None:
            return
        try:
            from cosmo_dl.config import save_token

            save_token(
                auth.source_name,
                {
                    "refresh_token": auth.refresh_token,
                    "access_token": auth.access_token,
                    "token_expiry": auth.token_expiry,
                },
            )
        except Exception as exc:
            logger.debug("Failed to persist OAuth2 tokens: %s", exc)

    def _refresh_oauth2_token(self) -> bool:
        """Refresh the OAuth2 access token using the stored refresh token.

        Returns ``True`` if a fresh token was obtained.
        """
        auth = self._oauth2_auth
        if auth is None:
            return False
        if not auth.refresh_token or not auth.token_url:
            logger.warning("OAuth2: missing refresh_token or token_url, cannot refresh")
            return False

        payload: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": auth.refresh_token,
        }
        if auth.client_id:
            payload["client_id"] = auth.client_id
        if auth.client_secret:
            payload["client_secret"] = auth.client_secret
        if auth.scopes:
            payload["scope"] = auth.scopes

        try:
            resp = requests.post(
                auth.token_url,
                data=payload,
                timeout=(10, 30),
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("OAuth2 token refresh failed: %s", exc)
            return False

        new_access = data.get("access_token")
        if not new_access:
            logger.warning("OAuth2: no access_token in refresh response")
            return False

        auth.access_token = new_access
        expires_in = data.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            auth.token_expiry = time.time() + float(expires_in)
        else:
            auth.token_expiry = None

        # Update session header
        self._client.headers["Authorization"] = f"Bearer {auth.access_token}"

        # Persist updated tokens
        self._persist_oauth2_tokens()
        logger.info("OAuth2 token refreshed successfully")
        return True

    def _ensure_fresh_token(self) -> None:
        """Check if the OAuth2 access token is expired and refresh if needed."""
        auth = self._oauth2_auth
        if auth is None or auth.access_token is None:
            return
        if auth.token_expiry is not None and time.time() >= auth.token_expiry - 60:
            self._refresh_oauth2_token()

    # ------------------------------------------------------------------
    # HTTP methods (with OAuth2 auto-refresh)
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()
        self._closed = True

    @property
    def is_closed(self) -> bool:
        """Return True if the session has been closed."""
        return self._closed

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
