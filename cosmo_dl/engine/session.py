"""HTTP session manager wrapping httpx.Client with auth, retry, and proxy support."""
from __future__ import annotations

import http.cookiejar
from typing import Any

import httpx

from cosmo_dl.engine.types import AuthConfig


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
        Number of retries for failed requests (default 3).
    retry_backoff : float
        Backoff factor for retries (default 0.5).
    timeout : int
        Request timeout in seconds (default 30).
    proxy : str or None
        Proxy URL (e.g. "http://proxy:8080").
    """

    def __init__(
        self,
        auth: AuthConfig | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        retry: int = 3,
        retry_backoff: float = 0.5,
        timeout: int = 30,
        proxy: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.retry = retry
        self.retry_backoff = retry_backoff

        # Build auth for httpx.Client
        httpx_auth: httpx.Auth | None = None
        extra_headers: dict[str, str] = {}
        extra_cookies: dict[str, str] | http.cookiejar.CookieJar | None = None

        if auth is not None:
            # Apply custom headers from AuthConfig
            if auth.custom_headers:
                extra_headers.update(auth.custom_headers)

            if auth.type == "basic" and auth.username is not None and auth.password is not None:
                httpx_auth = httpx.BasicAuth(auth.username, auth.password)
            elif auth.type == "bearer" and auth.token is not None:
                extra_headers["authorization"] = f"Bearer {auth.token}"
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

        # Handle cookies: user-supplied dict takes precedence, or use cookiejar
        merged_cookies: Any = None
        if extra_cookies is not None:
            merged_cookies = extra_cookies
        if cookies:
            if merged_cookies is not None:
                # Cookies as dict overwrite cookiejar entries
                for k, v in cookies.items():
                    if isinstance(merged_cookies, http.cookiejar.CookieJar):
                        # Add dict cookies to the client separately via `cookies` param
                        pass
            merged_cookies = cookies

        # Build transport with retry and proxy support
        transport = httpx.HTTPTransport(retries=retry, proxy=proxy)

        self._client = httpx.Client(
            auth=httpx_auth,
            headers=merged_headers if merged_headers else None,
            cookies=merged_cookies if merged_cookies else None,
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )

    @property
    def client(self) -> httpx.Client:
        """Return the underlying httpx.Client."""
        return self._client

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a HEAD request."""
        return self._client.head(url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a GET request."""
        return self._client.get(url, **kwargs)

    def stream(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a GET request with streaming enabled."""
        method = kwargs.setdefault("method", "GET")
        kwargs.pop("method")
        return self._client.stream(method, url, **kwargs)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
