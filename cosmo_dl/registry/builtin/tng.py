"""IllustrisTNG simulation data source — lazy tree structure.

Levels::

    TNG/                        root group
      TNG50/                    sub-group (by simulation base name)
        TNG50-1/                simulation
          groupcat/             file category (→ lists indices)
          snapshots/
          ...
      TNG100/
        TNG100-1/
          ...
      TNG300/
      TNG-Cluster/
      Illustris/

Each level is loaded lazily with a single API call to the TNG REST API.
In offline mode a built-in fallback list is used.
"""
from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from fnmatch import fnmatch

import httpx

from cosmo_dl.config import get as config_get
from cosmo_dl.engine.types import AuthConfig
from cosmo_dl.registry.source import SourceNode

logger = logging.getLogger(__name__)

TNG_API_BASE = "https://www.tng-project.org/api/"
TNG_GROUP = "TNG"

# ---------------------------------------------------------------------------
# Fallback simulation list
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
# Helpers
# ---------------------------------------------------------------------------

def _is_offline() -> bool:
    return os.environ.get("COSMO_DL_OFFLINE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _make_auth() -> AuthConfig | None:
    api_key = config_get("tng_api_key")
    if api_key:
        return AuthConfig(type="api-key", token=api_key)
    return None


def _make_client() -> httpx.Client | None:
    auth = _make_auth()
    if auth is None:
        return None
    client = httpx.Client(timeout=httpx.Timeout(30))
    if auth.type == "api-key" and auth.token:
        client.headers["api-key"] = auth.token
    if auth.custom_headers:
        client.headers.update(auth.custom_headers)
    return client


def _sub_group(name: str) -> str:
    """Extract the sub-group name from a simulation name.

    >>> _sub_group("TNG50-1")       → "TNG50"
    >>> _sub_group("TNG100-1-Dark") → "TNG100"
    >>> _sub_group("Illustris-1")   → "Illustris"
    >>> _sub_group("TNG-Cluster")   → "TNG-Cluster"
    """
    # Strip known suffixes
    base = name
    for suffix in ("-Dark", "-BHs", "-CRs"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    # Strip trailing run number: "TNG50-1" → "TNG50", "Illustris-1" → "Illustris"
    m = re.match(r"^(.+?)-\d+$", base)
    if m:
        return m.group(1)
    return base


# ---------------------------------------------------------------------------
# API fetchers (one level at a time)
# ---------------------------------------------------------------------------

def _fetch_simulations() -> list[tuple[str, str]]:
    """Fetch the list of simulations from the TNG API root.

    Returns list of (name, description).  Falls back on error.
    """
    if _is_offline():
        return list(_FALLBACK_SIMULATIONS)

    client = _make_client()
    if client is None:
        return list(_FALLBACK_SIMULATIONS)

    try:
        resp = client.get(TNG_API_BASE)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("TNG API root failed: %s. Using fallback.", exc)
        return list(_FALLBACK_SIMULATIONS)
    finally:
        client.close()

    sims = data.get("simulations")
    if not isinstance(sims, list) or not sims:
        logger.warning(
            "TNG API returned no simulation list (maybe invalid API key?). "
            "Using fallback list."
        )
        return list(_FALLBACK_SIMULATIONS)

    return [(s.get("name", ""), s.get("description", s.get("title", ""))) for s in sims if s.get("name")]


def _fetch_categories(sim_name: str) -> dict[str, list[int]]:
    """Fetch file categories for a simulation.

    Returns dict of category_name → list of indices.
    Falls back to a sensible default when the API is unreachable
    or returns unexpected data (e.g. wrong API key).
    """
    fallback = {"groupcat": list(range(100)), "snapshots": list(range(100))}

    if _is_offline():
        return fallback

    client = _make_client()
    if client is None:
        return fallback

    url = f"{TNG_API_BASE}{sim_name}/"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return fallback
    finally:
        client.close()

    # A valid TNG response has a "files" key with category→indices mapping.
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        logger.warning(
            "TNG API returned unexpected data for %s (maybe invalid API key?). "
            "Using fallback categories.", sim_name,
        )
        return fallback

    result: dict[str, list[int]] = {}
    for cat_name, indices in files.items():
        if isinstance(indices, list) and indices:
            result[cat_name] = sorted(indices)

    # If we got zero usable categories, use fallback
    if not result:
        return fallback
    return result


# ---------------------------------------------------------------------------
# Tree builders (each returns a dict of SourceNode children)
# ---------------------------------------------------------------------------

def _build_categories_children(sim_name: str, base_url: str) -> dict[str, SourceNode]:
    """Build children for a simulation node: one child per file category."""
    categories = _fetch_categories(sim_name)
    children: dict[str, SourceNode] = {}

    for cat_name, indices in sorted(categories.items()):
        # Each index → a dataset node
        index_children: dict[str, SourceNode] = {}
        for idx in indices:
            ds_name = f"{cat_name}-{idx}"
            api_url = f"{base_url}files/{cat_name}-{idx}/"
            index_children[ds_name] = SourceNode(
                name=ds_name,
                path=f"TNG/{_sub_group(sim_name)}/{sim_name}/{cat_name}/{ds_name}",
                description=f"{sim_name} {cat_name}, index {idx}",
                node_type="dataset",
                url=api_url,
                children={},
                child_count=0,
            )

        cat_desc = f"{len(indices)} indices (0–{indices[-1]})" if indices else "empty"
        children[cat_name] = SourceNode(
            name=cat_name,
            path=f"TNG/{_sub_group(sim_name)}/{sim_name}/{cat_name}",
            description=f"{sim_name} {cat_name} — {cat_desc}",
            node_type="category",
            child_count=len(indices),
            children=index_children,
        )

    return children


def _build_sim_loader(sim_name: str) -> callable:
    """Return a lazy loader for a simulation's file categories."""
    base_url = f"{TNG_API_BASE}{sim_name}/"
    def load() -> dict[str, SourceNode]:
        return _build_categories_children(sim_name, base_url)
    return load


def _build_subgroup_children(
    sims: list[tuple[str, str]],
    auth: AuthConfig | None,
) -> dict[str, SourceNode]:
    """Build children for a sub-group node: one child per simulation in this group."""
    children: dict[str, SourceNode] = {}
    for name, desc in sims:
        children[name] = SourceNode(
            name=name,
            path=f"TNG/{_sub_group(name)}/{name}",
            description=desc,
            node_type="category",
            child_count=0,  # unknown until loaded
            _loader=_build_sim_loader(name),
            auth=auth,
        )
    return children


def _build_tng_children(auth: AuthConfig | None) -> dict[str, SourceNode]:
    """Build the top-level TNG children: sub-groups (TNG50, TNG100, ...)."""
    sims = _fetch_simulations()

    # Group by sub_group
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, desc in sims:
        groups[_sub_group(name)].append((name, desc))

    children: dict[str, SourceNode] = {}
    for group_name, group_sims in sorted(groups.items()):
        group_desc = _describe_sub_group(group_name, len(group_sims))
        children[group_name] = SourceNode(
            name=group_name,
            path=f"TNG/{group_name}",
            description=group_desc,
            node_type="group",
            child_count=len(group_sims),
            _loader=lambda g=group_sims, a=auth: _build_subgroup_children(g, a),
            auth=auth,
        )
    return children


def _describe_sub_group(name: str, count: int) -> str:
    """Human-readable description for a TNG sub-group."""
    descriptions = {
        "TNG50": "TNG 50 Mpc/h box",
        "TNG100": "TNG 100 Mpc/h box",
        "TNG300": "TNG 300 Mpc/h box",
        "TNG-Cluster": "TNG cluster zoom",
        "Illustris": "Original Illustris 75 Mpc/h box",
    }
    base = descriptions.get(name, name)
    return f"{base} — {count} simulation(s)"


# ---------------------------------------------------------------------------
# Public API: build the TNG root node
# ---------------------------------------------------------------------------

def build_tng_root() -> SourceNode:
    """Return the TNG root SourceNode.

    Children (sub-groups) are loaded lazily via the TNG API.
    """
    auth = _make_auth()

    # Count total simulations (use fallback in offline mode)
    if _is_offline():
        sim_count = len(_FALLBACK_SIMULATIONS)
    else:
        client = _make_client()
        if client is not None:
            try:
                resp = client.get(TNG_API_BASE)
                resp.raise_for_status()
                sim_count = len(resp.json().get("simulations", []))
            except Exception:
                sim_count = len(_FALLBACK_SIMULATIONS)
            finally:
                client.close()
        else:
            sim_count = len(_FALLBACK_SIMULATIONS)

    return SourceNode(
        name="TNG",
        path="TNG",
        description=f"IllustrisTNG project — {sim_count} simulation(s)",
        node_type="group",
        child_count=sim_count,
        _loader=lambda a=auth: _build_tng_children(a),
        auth=auth,
    )
