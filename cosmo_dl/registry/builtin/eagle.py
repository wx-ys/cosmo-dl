"""EAGLE simulation data source — lazy tree via HTTP directory scraping.

The EAGLE (Evolution and Assembly of GaLaxies and their Environments)
simulations are a suite of cosmological hydrodynamical simulations performed
with a modified version of the GADGET-3 code.

Tree structure (auto-discovered from the HTTP directory listing)::

    EAGLE/                             root group
      <simulation_run>/                individual simulation run directory
        ...

HTTP Basic Authentication is required.  Credentials are read from
environment variables (``COSMO_EAGLE_USERNAME``, ``COSMO_EAGLE_PASSWORD``),
``.env`` files, or the TOML config file (``eagle_username``, ``eagle_password``).

Each level is loaded lazily with a single HTTP GET to the directory URL.
HTML directory listings are parsed to discover files and subdirectories.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from cosmo_dl.config import get as config_get
from cosmo_dl.registry.source import SourceNode

logger = logging.getLogger(__name__)

EAGLE_BASE_URL = "https://dataweb.cosma.dur.ac.uk:8443/eagle-snapshots/"

# ---------------------------------------------------------------------------
# HTML directory listing parsing
# ---------------------------------------------------------------------------

# Regex to extract <a href="...">text</a> from HTML directory listings
_A_TAG_RE = re.compile(
    r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>',
    re.IGNORECASE,
)

# Href prefixes that should never be followed
_SKIP_HREF_PREFIXES = ("#", "?", "javascript:", "mailto:")

# Link text that should be skipped (parent dir, self)
_SKIP_NAMES = {"..", ".", "../", "./"}

# Strip nested HTML tags from link text (e.g. <img> icons inside <a>)
_STRIP_TAGS_RE = re.compile(r"<[^>]*>")

# File names to skip when scraping (server-generated pages, not data)
_SKIP_FILE_NAMES: set[str] = {
    "index.html", "index.htm", "index.php",
    "header.html", "footer.html",
    ".htaccess", ".gitignore",
}

# Timeout for directory scraping: (connect, read)
_SCRAPE_TIMEOUT = (10, 60)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_eagle_auth() -> HTTPBasicAuth | None:
    """Return HTTPBasicAuth if EAGLE credentials are configured, or ``None``."""
    username = config_get("eagle_username")
    password = config_get("eagle_password")
    if username and password:
        return HTTPBasicAuth(username, password)
    return None


def _get_eagle_session() -> requests.Session | None:
    """Create a requests.Session with EAGLE Basic Auth, or ``None``."""
    auth = _get_eagle_auth()
    if auth is None:
        return None
    session = requests.Session()
    session.auth = auth
    return session


# ---------------------------------------------------------------------------
# Directory scraper
# ---------------------------------------------------------------------------


def _scrape_dir(url: str) -> list[tuple[str, str, bool]]:
    """Scrape a single level of an HTML directory listing.

    Parameters
    ----------
    url : str
        Directory URL to scrape (should end with ``/``).

    Returns
    -------
    list[tuple[str, str, bool]]
        List of ``(name, full_url, is_dir)`` for each entry.
        Directory *name* values have a trailing ``/``.
        Returns an empty list on any error.
    """
    session = _get_eagle_session()
    if session is None:
        logger.warning("EAGLE: no credentials configured, cannot scrape %s", url)
        return []

    try:
        resp = session.get(url, timeout=_SCRAPE_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("Failed to scrape directory %s: %s", url, exc)
        return []
    finally:
        session.close()

    entries: list[tuple[str, str, bool]] = []
    seen: set[str] = set()

    for match in _A_TAG_RE.finditer(html):
        href = match.group(1)
        raw_text = match.group(2)

        # --- filter unwanted href prefixes --------------------------------
        if any(href.startswith(p) for p in _SKIP_HREF_PREFIXES):
            continue

        # --- clean up display name ---------------------------------------
        name = _STRIP_TAGS_RE.sub("", raw_text).strip()
        if not name:
            continue

        # --- skip parent / self links ------------------------------------
        if name in _SKIP_NAMES:
            continue

        # --- classify ----------------------------------------------------
        is_dir = name.endswith("/") or href.endswith("/")
        if is_dir and not name.endswith("/"):
            name += "/"

        # Deduplicate (some servers list the same entry twice)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        # --- skip server-generated pages ---------------------------------
        if not is_dir and name.lower() in _SKIP_FILE_NAMES:
            continue

        # --- skip hidden files / dotfiles --------------------------------
        if name.startswith("."):
            continue

        full_url = urljoin(url, href)
        entries.append((name, full_url, is_dir))

    # Sort: directories first (alphabetical), then files (alphabetical)
    entries.sort(key=lambda e: (not e[2], e[0].lower()))

    return entries


# ---------------------------------------------------------------------------
# Generic directory → children builder
# ---------------------------------------------------------------------------


def _build_dir_children(
    dir_url: str,
    path_prefix: str,
    relpath_prefix: str = "",
) -> dict[str, SourceNode]:
    """Build child ``SourceNode`` entries from an HTTP directory listing.

    Subdirectories become lazy-loaded ``category`` nodes (their children
    are scraped on demand).  Files become ``dataset`` leaf nodes with
    direct download URLs.

    Parameters
    ----------
    dir_url : str
        URL of the directory to scrape.
    path_prefix : str
        Tree path prefix for constructing child paths
        (e.g. ``"EAGLE"``).
    relpath_prefix : str
        Relative path prefix for ``download_relpath`` values
        (e.g. ``""``).

    Returns
    -------
    dict[str, SourceNode]
    """
    entries = _scrape_dir(dir_url)
    children: dict[str, SourceNode] = {}

    for name, full_url, is_dir in entries:
        node_name = name.rstrip("/")
        child_path = f"{path_prefix}/{node_name}"
        child_relpath = f"{relpath_prefix}{name}"

        if is_dir:
            def _make_loader(
                u: str = full_url,
                pp: str = child_path,
                rp: str = child_relpath,
            ):
                def _load() -> dict[str, SourceNode]:
                    return _build_dir_children(u, pp, rp)

                return _load

            children[node_name] = SourceNode(
                name=node_name,
                path=child_path,
                description="",
                node_type="category",
                child_count=0,  # discovered lazily
                _loader=_make_loader(),
                download_relpath=child_relpath,
            )
        else:
            children[node_name] = SourceNode(
                name=node_name,
                path=child_path,
                description="",
                node_type="dataset",
                url=full_url,
                children={},
                download_relpath=child_relpath,
            )

    return children


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_eagle_root() -> SourceNode:
    """Return the EAGLE root ``SourceNode``.

    Children (simulation run directories) are discovered lazily by scraping
    the EAGLE public data server.  Each level below that is also discovered
    on demand.

    HTTP Basic Authentication is required — set ``eagle_username`` and
    ``eagle_password`` via environment variables, ``.env`` files, or
    the TOML config file.

    Returns
    -------
    SourceNode
        Root node of the EAGLE source tree.  ``node_type`` is ``"group"``,
        ``name`` is ``"EAGLE"``.
    """

    def _load_children() -> dict[str, SourceNode]:
        return _build_dir_children(EAGLE_BASE_URL, "EAGLE", "")

    return SourceNode(
        name="EAGLE",
        path="EAGLE",
        description="EAGLE simulations (Virgo Consortium) — auto-discovered",
        node_type="group",
        child_count=0,  # discovered lazily
        _loader=_load_children,
        base_url=EAGLE_BASE_URL,
    )
