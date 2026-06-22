"""Globus Auth and Transfer API utilities for cosmo-dl.

Provides helpers for OAuth2 authentication against Globus Auth and
directory listing / file access on Globus Connect Server (GCS) endpoints.

No heavy SDK dependency — uses plain ``requests`` and stdlib.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Globus Auth endpoints
# ---------------------------------------------------------------------------

GLOBUS_AUTH_BASE = "https://auth.globus.org/v2/oauth2"
GLOBUS_AUTHORIZE_URL = f"{GLOBUS_AUTH_BASE}/authorize"
GLOBUS_TOKEN_URL = f"{GLOBUS_AUTH_BASE}/token"

# Default cosmo-dl client ID (must be registered at developers.globus.org).
# Users can override via COSMO_DL_GLOBUS_CLIENT_ID env var.
_GLOBUS_CLIENT_ID = ""


def get_globus_client_id() -> str:
    """Return the Globus Auth client ID from env or built-in default."""
    return os.environ.get("COSMO_DL_GLOBUS_CLIENT_ID", _GLOBUS_CLIENT_ID)


# ---------------------------------------------------------------------------
# Globus Auth scopes
# ---------------------------------------------------------------------------


def _https_scope(target: str) -> str:
    """Build the HTTPS access scope for a Globus collection or GCS endpoint.

    *target* may be a collection ID (UUID) or a GCS endpoint hostname.

    Example: ``02a2dbb8-f64d-4440-bafe-44b60b964501`` →
    ``https://auth.globus.org/scopes/02a2dbb8-f64d-4440-bafe-44b60b964501/https``
    """
    return f"https://auth.globus.org/scopes/{target}/https"


# ---------------------------------------------------------------------------
# PKCE (Proof Key for Code Exchange) — RFC 7636
# ---------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge pair.

    Returns
    -------
    tuple[str, str]
        ``(code_verifier, code_challenge)``
    """
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# ---------------------------------------------------------------------------
# OAuth2 authorization code flow
# ---------------------------------------------------------------------------


def build_authorize_url(
    client_id: str,
    scope: str,
    redirect_uri: str,
    code_challenge: str,
) -> str:
    """Build the Globus Auth authorization URL for the native app flow.

    Parameters
    ----------
    client_id : str
        Globus Auth client ID.
    scope : str
        OAuth2 scope string (e.g.
        ``https://auth.globus.org/scopes/<collection_id>/https``).
    redirect_uri : str
        OAuth2 redirect URI (e.g. ``http://localhost:8765/callback``).
    code_challenge : str
        PKCE code challenge (S256).

    Returns
    -------
    str
        Full authorization URL to open in the user's browser.
    """
    params = (
        f"client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&response_type=code"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&state=cosmo-dl"
    )
    return f"{GLOBUS_AUTHORIZE_URL}?{params}"


def exchange_code_for_tokens(
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, object] | None:
    """Exchange an authorization code for access + refresh tokens.

    Returns a dict with keys ``access_token``, ``refresh_token``,
    ``expires_in``, or ``None`` on failure.
    """
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    try:
        resp = requests.post(GLOBUS_TOKEN_URL, data=payload, timeout=(10, 30))
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("Globus token exchange failed: %s", exc)
        return None


def refresh_access_token(
    client_id: str,
    refresh_token: str,
    scope: str,
) -> dict[str, object] | None:
    """Refresh an expired access token using a refresh token.

    Returns a dict with ``access_token``, ``expires_in``, etc.,
    or ``None`` on failure.
    """
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "scope": scope,
    }
    try:
        resp = requests.post(GLOBUS_TOKEN_URL, data=payload, timeout=(10, 30))
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("Globus token refresh failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Globus HTTPS endpoint — directory listing
# ---------------------------------------------------------------------------

# Regex for HTML directory listing parsing (same approach as fire.py)
_A_TAG_RE = re.compile(
    r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE,
)
_SKIP_HREF_PREFIXES = ("#", "?", "javascript:", "mailto:")
_SKIP_NAMES = {"..", ".", "../", "./"}
_STRIP_TAGS_RE = re.compile(r"<[^>]*>")
_SKIP_FILE_NAMES: set[str] = {
    "index.html", "index.htm", "index.php",
    "header.html", "footer.html",
    ".htaccess", ".gitignore",
}


def list_globus_dir(
    dir_url: str,
    access_token: str,
    *,
    timeout: tuple[int, int] = (10, 60),
) -> list[tuple[str, str, bool]]:
    """List the contents of a directory on a Globus HTTPS endpoint.

    Parameters
    ----------
    dir_url : str
        Directory URL (e.g. ``https://g-...data.globus.org/level4/``).
    access_token : str
        Valid Globus Auth access token with ``https`` scope for the endpoint.

    Returns
    -------
    list[tuple[str, str, bool]]
        List of ``(name, full_url, is_dir)``.  Directory names have a
        trailing ``/``.  Returns empty list on error.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(dir_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("Failed to list Globus dir %s: %s", dir_url, exc)
        return []

    if not html.strip():
        logger.debug("Empty response from Globus dir %s (needs auth?)", dir_url)
        return []

    entries: list[tuple[str, str, bool]] = []
    seen: set[str] = set()

    for match in _A_TAG_RE.finditer(html):
        href = match.group(1)
        raw_text = match.group(2)

        if any(href.startswith(p) for p in _SKIP_HREF_PREFIXES):
            continue

        name = _STRIP_TAGS_RE.sub("", raw_text).strip()
        if not name or name in _SKIP_NAMES:
            continue

        is_dir = name.endswith("/") or href.endswith("/")
        if is_dir and not name.endswith("/"):
            name += "/"

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        if not is_dir and name.lower() in _SKIP_FILE_NAMES:
            continue
        if name.startswith("."):
            continue

        full_url = urljoin(dir_url, href)
        entries.append((name, full_url, is_dir))

    entries.sort(key=lambda e: (not e[2], e[0].lower()))
    return entries


# ---------------------------------------------------------------------------
# One-shot directory listing with token injection
# ---------------------------------------------------------------------------


def scrape_globus_dir(
    dir_url: str,
    access_token: str,
) -> list[tuple[str, str, bool]]:
    """Alias for :func:`list_globus_dir` — scrape a Globus HTTPS directory."""
    return list_globus_dir(dir_url, access_token)
