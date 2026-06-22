"""FIRE-2 simulation public data source — lazy tree via HTTP directory scraping.

Tree structure (auto-discovered from the public HTTP directory listing)::

    FIRE2/                             root group
      core/                            Core suite (20 sims to z=0)
        m11i_res7100/                  individual simulation
          output/                      snapshot data files
          ...
        m12i_res7100/
        ...
        dm_only/                       physics variation sub-suite
        reionize_later/                physics variation sub-suite
        mhd/                           physics variation sub-suite
        cosmic_ray/                    physics variation sub-suite
      massive_halo/                    Massive Halo suite (8 sims to z=1)
      high_redshift/                   High Redshift suite (34 sims)
      boxes/                           DM-only cosmological boxes (4 sims)

No API key required — FIRE-2 data is publicly accessible.
Each level is loaded lazily with a single HTTP GET to the directory URL.
HTML directory listings are parsed to discover files and subdirectories.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests

from cosmo_dl.registry.source import SourceNode

logger = logging.getLogger(__name__)

FIRE2_BASE_URL = "https://users.flatironinstitute.org/~mgrudic/fire2_public_release/"

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
    "index.html",
    "index.htm",
    "index.php",
    "header.html",
    "footer.html",
    ".htaccess",
    ".gitignore",
}

# Timeout for directory scraping: (connect, read)
_SCRAPE_TIMEOUT = (10, 60)

# ---------------------------------------------------------------------------
# Suite / sub-suite descriptions (from FIRE-2 README files)
# ---------------------------------------------------------------------------

_SUITE_DESCRIPTIONS: dict[str, str] = {
    "core": (
        "Core suite to z=0 — 20 simulations (14 MW-mass, 5 SMC/LMC-mass, "
        "4 lower-mass) with FIRE-2 base physics; 601 snapshots; "
        "Rockstar halo/galaxy catalogs & Consistent Trees merger trees; "
        "particle tracking with 3-D formation coordinates for stars"
    ),
    "massive_halo": (
        "Massive Halo suite to z=1 — 8 simulations; 278 snapshots; "
        "Rockstar halo catalogs at 19 snapshots (DR1), "
        "AHF catalogs at almost all snapshots; no merger trees"
    ),
    "high_redshift": (
        "High Redshift suite — 34 simulations: "
        "22 to z=5 (z5* prefix, 67 snapshots; Rockstar & AHF halo catalogs), "
        "6 to z=7 (z7* prefix, 41 snapshots; AHF only), "
        "6 to z=9 (z9* prefix, 26 snapshots; AHF only); no merger trees"
    ),
    "boxes": (
        "DM-only cosmological boxes to z=0 — 4 simulations "
        "(86, 108, 136, 172 Mpc); 11 snapshots "
        "(snapshot 0 = ICs at z=99); Rockstar halo catalogs; "
        "L172 has merger trees; "
        "cosmology: h=0.68, Ω_Λ=0.69, Ω_m=0.31, Ω_b=0.048, σ_8=0.82, n_s=0.97"
    ),
}

_CORE_VARIANT_DESCRIPTIONS: dict[str, str] = {
    "dm_only": (
        "Dark Matter Only — 19 simulations, 61 snapshots; "
        "halo catalogs with merger trees across all ~600 snapshots "
        "(physics variation)"
    ),
    "reionize_later": (
        "Later Reionization (z_reion=7.8) — 4 simulations, 601 snapshots; "
        "halo/galaxy catalogs, merger trees & particle tracking "
        "(physics variation)"
    ),
    "mhd": (
        "MHD+ (magnetohydrodynamics + anisotropic conduction & viscosity) "
        "— 16 simulations, 61 snapshots; "
        "m12f/m12i/m12m have more snapshots, catalogs, "
        "merger trees & particle tracking (physics variation)"
    ),
    "cosmic_ray": (
        "Cosmic Ray (MHD+ + cosmic ray injection, transport & feedback) "
        "— 14 simulations, 61 snapshots; "
        "m12f/m12i/m12m have all 601 snapshots, catalogs, "
        "merger trees & particle tracking (physics variation)"
    ),
}


def _description_for(name: str, parent: str = "") -> str:
    """Return a human-readable description for a known suite or variant.

    Parameters
    ----------
    name : str
        Directory name (without trailing slash).
    parent : str
        Name of the parent directory, used to disambiguate sub-suites.
    """
    if parent == "core" and name in _CORE_VARIANT_DESCRIPTIONS:
        return _CORE_VARIANT_DESCRIPTIONS[name]
    if name in _SUITE_DESCRIPTIONS:
        return _SUITE_DESCRIPTIONS[name]
    return ""


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
    try:
        resp = requests.get(url, timeout=_SCRAPE_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("Failed to scrape directory %s: %s", url, exc)
        return []

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
    *,
    parent_name: str = "",
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
        (e.g. ``"FIRE2/core"``).
    relpath_prefix : str
        Relative path prefix for ``download_relpath`` values
        (e.g. ``"core/"``).
    parent_name : str
        Name of the parent directory, used to look up sub-suite descriptions.

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
            desc = _description_for(node_name, parent=parent_name)

            def _make_loader(
                u: str = full_url,
                pp: str = child_path,
                rp: str = child_relpath,
                pn: str = node_name,
            ):
                def _load() -> dict[str, SourceNode]:
                    return _build_dir_children(u, pp, rp, parent_name=pn)

                return _load

            children[node_name] = SourceNode(
                name=node_name,
                path=child_path,
                description=desc,
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


def build_fire2_root() -> SourceNode:
    """Return the FIRE-2 root ``SourceNode``.

    Children (suite directories: ``core/``, ``massive_halo/``,
    ``high_redshift/``, ``boxes/``) are discovered lazily by scraping
    the FIRE-2 public release base URL.  Each level below that is also
    discovered on demand.

    No API key or authentication is required — FIRE-2 data is publicly
    accessible.

    Returns
    -------
    SourceNode
        Root node of the FIRE-2 source tree.  ``node_type`` is ``"group"``,
        ``name`` is ``"FIRE2"``.
    """

    def _load_children() -> dict[str, SourceNode]:
        return _build_dir_children(FIRE2_BASE_URL, "FIRE2", "")

    return SourceNode(
        name="FIRE2",
        path="FIRE2",
        description="FIRE-2 public release (Flatiron Institute) — auto-discovered",
        node_type="group",
        child_count=0,  # discovered lazily
        _loader=_load_children,
        base_url=FIRE2_BASE_URL,
    )
