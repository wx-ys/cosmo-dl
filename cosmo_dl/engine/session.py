"""HTTP session manager wrapping requests.Session with auth, retry, and proxy support."""
from __future__ import annotations

import http.cookiejar
from typing import Any, ContextManager
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cosmo_dl.engine.types import AuthConfig


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

        # Build extra headers from auth config
        extra_headers: dict[str, str] = {}
        extra_cookies: dict[str, str] | http.cookiejar.CookieJar | None = None

        if auth is not None:
            if auth.custom_headers:
                extra_headers.update(auth.custom_headers)

            if auth.type == "basic" and auth.username is not None and auth.password is not None:
                # requests handles BasicAuth via the session's .auth attribute
                self._requests_auth: requests.auth.AuthBase | None = \
                    requests.auth.HTTPBasicAuth(auth.username, auth.password)
            else:
                self._requests_auth = None

            if auth.type == "bearer" and auth.token is not None:
                extra_headers["Authorization"] = f"Bearer {auth.token}"
            elif auth.type == "api-key" and auth.token is not None:
                extra_headers["api-key"] = auth.token
            elif auth.type == "cookie" and auth.cookie_file is not None:
                cj = http.cookiejar.MozillaCookieJar()
                try:
                    cj.load(auth.cookie_file, ignore_discard=True, ignore_expires=True)
                except FileNotFoundError:
                    pass
                extra_cookies = cj

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

        if hasattr(self, '_requests_auth') and self._requests_auth is not None:
            self._client.auth = self._requests_auth

        # Set up retry adapter
        retry_strategy = Retry(
            total=retry,
            backoff_factor=retry_backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(['GET', 'HEAD', 'OPTIONS']),
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=100,
            pool_maxsize=100,
        )
        self._client.mount('http://', adapter)
        self._client.mount('https://', adapter)

        # Proxy
        if proxy:
            self._client.proxies.update({'http': proxy, 'https': proxy})

    @property
    def client(self) -> requests.Session:
        """Return the underlying requests.Session."""
        return self._client

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        """Send a HEAD request."""
        kwargs.setdefault('timeout', self._timeout)
        return self._client.head(url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Send a GET request."""
        kwargs.setdefault('timeout', self._timeout)
        return self._client.get(url, **kwargs)

    def stream(self, url: str, **kwargs: Any) -> ContextManager[StreamResponse]:
        """Send a GET request with streaming enabled.

        Returns a context manager yielding a :class:`StreamResponse` that
        provides ``headers``, ``status_code``, ``raise_for_status()``, and
        ``iter_bytes(chunk_size)`` — compatible with the old httpx-based API.
        """
        kwargs.setdefault('timeout', self._timeout)
        # Pop any 'method' kwarg (httpx compatibility)
        kwargs.pop('method', None)
        resp = self._client.get(url, stream=True, **kwargs)
        return StreamResponse(resp)

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
