"""IllustrisTNG simulation data source.

Auto-discovers available simulations from the TNG REST API
(https://www.tng-project.org/api/).  Falls back to a hard-coded
list when the API is unreachable, no API key is configured, or
``COSMO_DL_OFFLINE`` is set.

Requires an API key from https://www.tng-project.org (free registration).

Set the key using any of these methods (highest priority first):

1. Environment variable: ``export TNG_API_KEY="your-key"``
2. ``.env`` file (``./.env`` or ``~/.config/cosmo-dl/.env``)
3. CLI command: ``cosmo-dl config set tng_api_key "your-key"``
"""
from __future__ import annotations

import logging
import os
from fnmatch import fnmatch

import httpx

from cosmo_dl.config import get as config_get
from cosmo_dl.engine.types import AuthConfig
from cosmo_dl.registry.source import DatasetInfo, SimulationSource

logger = logging.getLogger(__name__)

TNG_API_BASE = "http://www.tng-project.org/api/"
TNG_GROUP = "TNG"


def _is_offline() -> bool:
    """Check if offline mode is active (COSMO_DL_OFFLINE env var)."""
    return os.environ.get("COSMO_DL_OFFLINE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )

# ---------------------------------------------------------------------------
# Fallback: hard-coded list used when the API cannot be reached
# ---------------------------------------------------------------------------

_FALLBACK_SIMULATIONS = [
    ("TNG50-1", "TNG 50 Mpc/h, full physics"),
    ("TNG100-1", "TNG 100 Mpc/h, full physics"),
    ("TNG100-2", "TNG 100 Mpc/h, full physics (run 2)"),
    ("TNG100-3", "TNG 100 Mpc/h, full physics (run 3)"),
    ("TNG300-1", "TNG 300 Mpc/h, full physics"),
    ("TNG300-2", "TNG 300 Mpc/h, full physics (run 2)"),
    ("TNG100-1-Dark", "TNG 100 Mpc/h, dark matter only"),
    ("TNG100-2-Dark", "TNG 100 Mpc/h, dark matter only (run 2)"),
    ("TNG100-3-Dark", "TNG 100 Mpc/h, dark matter only (run 3)"),
    ("TNG300-1-Dark", "TNG 300 Mpc/h, dark matter only"),
    ("TNG300-2-Dark", "TNG 300 Mpc/h, dark matter only (run 2)"),
    ("TNG-Cluster", "TNG cluster zoom, full physics"),
    ("Illustris-1", "Original Illustris 75 Mpc/h box"),
    ("Illustris-2", "Original Illustris 75 Mpc/h box (run 2)"),
    ("Illustris-3", "Original Illustris 75 Mpc/h box (run 3)"),
    ("Illustris-1-Dark", "Original Illustris 75 Mpc/h, dark matter only"),
    ("Illustris-2-Dark", "Original Illustris 75 Mpc/h, dark matter only (run 2)"),
]

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _make_auth() -> AuthConfig | None:
    """Resolve the TNG API key from all configured sources."""
    api_key = config_get("tng_api_key")
    if api_key:
        return AuthConfig(type="api-key", token=api_key)
    return None


def _make_client() -> httpx.Client | None:
    """Create an httpx Client with TNG auth headers, or None."""
    auth = _make_auth()
    if auth is None:
        return None
    client = httpx.Client(timeout=httpx.Timeout(30))
    if auth.type == "api-key" and auth.token:
        client.headers["api-key"] = auth.token
    if auth.custom_headers:
        client.headers.update(auth.custom_headers)
    return client


# ---------------------------------------------------------------------------
# API discovery
# ---------------------------------------------------------------------------

def discover_tng_simulations(
    *,
    include: str = "*",
    exclude: str | None = None,
) -> list[tuple[str, str]]:
    """Query the TNG API and return a list of (name, description) tuples.

    Parameters
    ----------
    include : str
        ``fnmatch`` glob to filter simulation names (default ``"*"``).
    exclude : str or None
        ``fnmatch`` glob to exclude simulation names.

    Returns
    -------
    list[tuple[str, str]]
        Each element is ``(simulation_name, description)``.

    If the API is unreachable, the fallback list is returned.
    """
    if _is_offline():
        logger.info("COSMO_DL_OFFLINE set — using fallback simulation list")
        return _filter_sims(_FALLBACK_SIMULATIONS, include, exclude)

    client = _make_client()
    if client is None:
        logger.info("No TNG API key configured — using fallback simulation list")
        return _filter_sims(_FALLBACK_SIMULATIONS, include, exclude)

    try:
        resp = client.get(TNG_API_BASE)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(
            "Failed to query TNG API at %s: %s. Using fallback list.",
            TNG_API_BASE, exc,
        )
        return _filter_sims(_FALLBACK_SIMULATIONS, include, exclude)
    finally:
        client.close()

    simulations_raw = data.get("simulations", [])
    if not simulations_raw:
        logger.info("TNG API returned no simulations — using fallback list")
        return _filter_sims(_FALLBACK_SIMULATIONS, include, exclude)

    result: list[tuple[str, str]] = []
    for sim in simulations_raw:
        name = sim.get("name", "")
        desc = sim.get("description", sim.get("title", name))
        if name:
            result.append((name, desc))

    return _filter_sims(result, include, exclude)


def discover_file_categories(sim_name: str) -> dict[str, str]:
    """Query the TNG API for a simulation's file categories.

    Returns a dict mapping category name → API path suffix.

    Example return: ``{"groupcat": "files/groupcat-", "snapshots": "files/snapshot-"}``
    """
    if _is_offline():
        return {}

    client = _make_client()
    if client is None:
        return {}

    url = f"{TNG_API_BASE}{sim_name}/"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}
    finally:
        client.close()

    # The "files" key contains categories like:
    # {"groupcat": [0, 1, ...], "snapshots": [0, 1, ...], ...}
    files = data.get("files", {})
    categories: dict[str, str] = {}
    for cat_name, indices in files.items():
        if isinstance(indices, list) and indices:
            categories[cat_name] = f"files/{cat_name}-"

    return categories


# ---------------------------------------------------------------------------
# Build sources
# ---------------------------------------------------------------------------

def _filter_sims(
    sims: list[tuple[str, str]],
    include: str,
    exclude: str | None,
) -> list[tuple[str, str]]:
    """Filter a list of (name, description) tuples by glob patterns."""
    result = []
    for name, desc in sims:
        if not fnmatch(name, include):
            continue
        if exclude and fnmatch(name, exclude):
            continue
        result.append((name, desc))
    return result


def _make_tng_source(name: str, description: str) -> SimulationSource:
    """Build a TNG simulation source with standard datasets.

    Each source exposes:
    - ``groupcat-{N}`` — group catalog for snapshot N (N=0..99)
    - ``snapshot-{N}`` — snapshot data for snapshot N (N=0..99)
    - Plus any additional categories discovered from the API.
    """
    base_url = f"{TNG_API_BASE}{name}/"

    datasets: dict[str, DatasetInfo] = {}

    # Try to discover file categories from the API
    categories = discover_file_categories(name)

    if categories:
        # Build datasets from API-discovered categories
        for cat_name, path_prefix in sorted(categories.items()):
            # Each category has indices like [0, 1, ..., 99]
            # We expose each index as a separate dataset
            for i in range(100):
                ds_name = f"{cat_name}-{i}"
                if ds_name not in datasets:
                    datasets[ds_name] = DatasetInfo(
                        path=f"{path_prefix}{i}/",
                        description=f"{name} {cat_name}, index {i}",
                    )
    else:
        # Fallback: standard groupcat + snapshot datasets (0-99)
        for i in range(100):
            datasets[f"groupcat-{i}"] = DatasetInfo(
                path=f"files/groupcat-{i}/",
                description=f"{name} group catalog, snapshot {i}",
            )
        for i in range(100):
            datasets[f"snapshot-{i}"] = DatasetInfo(
                path=f"files/snapshot-{i}/",
                description=f"{name} snapshot {i}",
            )

    return SimulationSource(
        name=name,
        description=description,
        base_url=base_url,
        auth=_make_auth(),
        structure="mirror",
        datasets=datasets,
        group=TNG_GROUP,
    )


def get_tng_sources(
    include: str = "*",
    exclude: str | None = None,
) -> list[SimulationSource]:
    """Return SimulationSource objects for all discovered TNG simulations.

    Parameters
    ----------
    include : str
        Glob pattern to filter simulation names.
    exclude : str or None
        Glob pattern to exclude simulation names.

    Returns
    -------
    list[SimulationSource]
    """
    sims = discover_tng_simulations(include=include, exclude=exclude)
    return [_make_tng_source(name, desc) for name, desc in sims]
