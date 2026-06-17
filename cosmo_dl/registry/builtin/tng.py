"""IllustrisTNG simulation data source — lazy tree structure.

Levels::

    TNG/                            root group
      TNG50/                        sub-group (by box size / project)
        TNG50-1/                    simulation (main) + data categories
          snapshots/                → snapshot listing
            sn-0/                   → individual snapshot
              snapshot/             → snapshot file chunks (→ output/snapdir_NNN/)
              groupcat/             → group catalog file chunks (→ output/groups_NNN/)
            sn-99/
          postprocessing/           → trees + offsets
            trees/
              LHaloTree/            → lhalotree file list
              SubLink/              → sublink file list
            offsets/                → offsets data
          files/                    → catalogs & postprocessing files
          subboxes/                 → child subbox simulations
          TNG50-1-Dark/             → dark matter variant (peer)
        TNG50-2/                    → 8× fewer particles (2× lower res.)
      TNG100/
      TNG300/
      TNG-Cluster/
      Illustris/

Resolution levels: -1 = highest, -2 = 8× fewer particles, -3 = 64× fewer, etc.
Only ics.hdf5 & simulation.hdf5 go to output/; all other single files → postprocessing/.

Each level is loaded lazily with a single API call to the TNG REST API.
In offline mode a built-in fallback list is used.
"""
from __future__ import annotations

import logging
import os
import re
from collections import defaultdict

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

_RESOLUTION_DESC = {
    1: "highest resolution",
    2: "8× fewer particles (2× lower resolution)",
    3: "64× fewer particles (4× lower resolution)",
    4: "512× fewer particles (8× lower resolution)",
}

_FALLBACK_SIMULATIONS: list[tuple[str, str, int, bool]] = [
    # (name, description, num_snapshots, is_subbox)
    ("TNG50-1",           "TNG 50 Mpc/h, full physics, highest resolution",       100, False),
    ("TNG50-1-Dark",      "TNG 50 Mpc/h, dark matter only, highest resolution",   100, False),
    ("TNG50-2",           "TNG 50 Mpc/h, full physics, 8× fewer particles (2× lower res.)", 100, False),
    ("TNG50-2-Dark",      "TNG 50 Mpc/h, dark matter only, 8× fewer particles (2× lower res.)", 100, False),
    ("TNG50-3",           "TNG 50 Mpc/h, full physics, 64× fewer particles (4× lower res.)", 100, False),
    ("TNG50-3-Dark",      "TNG 50 Mpc/h, dark matter only, 64× fewer particles (4× lower res.)", 100, False),
    ("TNG50-4",           "TNG 50 Mpc/h, full physics, 512× fewer particles (8× lower res.)", 100, False),
    ("TNG50-4-Dark",      "TNG 50 Mpc/h, dark matter only, 512× fewer particles (8× lower res.)", 100, False),
    ("TNG100-1",          "TNG 100 Mpc/h, full physics, highest resolution",      100, False),
    ("TNG100-1-Dark",     "TNG 100 Mpc/h, dark matter only, highest resolution",  100, False),
    ("TNG100-2",          "TNG 100 Mpc/h, full physics, 8× fewer particles (2× lower res.)", 100, False),
    ("TNG100-2-Dark",     "TNG 100 Mpc/h, dark matter only, 8× fewer particles (2× lower res.)", 100, False),
    ("TNG100-3",          "TNG 100 Mpc/h, full physics, 64× fewer particles (4× lower res.)", 100, False),
    ("TNG100-3-Dark",     "TNG 100 Mpc/h, dark matter only, 64× fewer particles (4× lower res.)", 100, False),
    ("TNG300-1",          "TNG 300 Mpc/h, full physics, highest resolution",      100, False),
    ("TNG300-1-Dark",     "TNG 300 Mpc/h, dark matter only, highest resolution",  100, False),
    ("TNG300-2",          "TNG 300 Mpc/h, full physics, 8× fewer particles (2× lower res.)", 100, False),
    ("TNG300-2-Dark",     "TNG 300 Mpc/h, dark matter only, 8× fewer particles (2× lower res.)", 100, False),
    ("TNG300-3",          "TNG 300 Mpc/h, full physics, 64× fewer particles (4× lower res.)", 100, False),
    ("TNG300-3-Dark",     "TNG 300 Mpc/h, dark matter only, 64× fewer particles (4× lower res.)", 100, False),
    ("TNG-Cluster",       "TNG cluster zoom, full physics, highest resolution",   100, False),
    ("Illustris-1",       "Original Illustris 75 Mpc/h, highest resolution",      134, False),
    ("Illustris-1-Dark",  "Original Illustris 75 Mpc/h, DM only, highest res.",   136, False),
    ("Illustris-2",       "Original Illustris 75 Mpc/h, 8× fewer particles (2× lower res.)", 136, False),
    ("Illustris-2-Dark",  "Original Illustris 75 Mpc/h, DM only, 8× fewer particles (2× lower res.)", 136, False),
    ("Illustris-3",       "Original Illustris 75 Mpc/h, 64× fewer particles (4× lower res.)", 136, False),
    ("Illustris-3-Dark",  "Original Illustris 75 Mpc/h, DM only, 64× fewer particles (4× lower res.)", 136, False),
    # Subboxes
    ("TNG50-1-Subbox0",   "TNG50-1 subbox 0",                         3600, True),
    ("TNG50-1-Subbox1",   "TNG50-1 subbox 1",                         3600, True),
    ("TNG50-1-Subbox2",   "TNG50-1 subbox 2",                         3600, True),
    ("TNG50-2-Subbox0",   "TNG50-2 subbox 0",                         1895, True),
    ("TNG50-2-Subbox1",   "TNG50-2 subbox 1",                         1895, True),
    ("TNG50-2-Subbox2",   "TNG50-2 subbox 2",                         1895, True),
    ("TNG50-3-Subbox0",   "TNG50-3 subbox 0",                         4006, True),
    ("TNG50-3-Subbox1",   "TNG50-3 subbox 1",                         4006, True),
    ("TNG50-3-Subbox2",   "TNG50-3 subbox 2",                         4006, True),
    ("TNG50-4-Subbox0",   "TNG50-4 subbox 0",                         2333, True),
    ("TNG50-4-Subbox1",   "TNG50-4 subbox 1",                         2333, True),
    ("TNG50-4-Subbox2",   "TNG50-4 subbox 2",                         2333, True),
    ("TNG100-1-Subbox0",  "TNG100-1 subbox 0",                        7908, True),
    ("TNG100-1-Subbox1",  "TNG100-1 subbox 1",                        7908, True),
    ("TNG100-2-Subbox0",  "TNG100-2 subbox 0",                        4380, True),
    ("TNG100-2-Subbox1",  "TNG100-2 subbox 1",                        4380, True),
    ("TNG100-3-Subbox0",  "TNG100-3 subbox 0",                        2431, True),
    ("TNG100-3-Subbox1",  "TNG100-3 subbox 1",                        2431, True),
    ("TNG300-1-Subbox0",  "TNG300-1 subbox 0",                        2449, True),
    ("TNG300-1-Subbox1",  "TNG300-1 subbox 1",                        2449, True),
    ("TNG300-1-Subbox2",  "TNG300-1 subbox 2",                        2449, True),
    ("TNG300-2-Subbox0",  "TNG300-2 subbox 0",                        3045, True),
    ("TNG300-2-Subbox1",  "TNG300-2 subbox 1",                        3045, True),
    ("TNG300-2-Subbox2",  "TNG300-2 subbox 2",                        3045, True),
    ("TNG300-3-Subbox0",  "TNG300-3 subbox 0",                        2050, True),
    ("TNG300-3-Subbox1",  "TNG300-3 subbox 1",                        2050, True),
    ("TNG300-3-Subbox2",  "TNG300-3 subbox 2",                        2050, True),
    ("Illustris-1-Subbox0","Illustris-1 subbox 0",                    3970, True),
    ("Illustris-1-Subbox1","Illustris-1 subbox 1",                    3969, True),
    ("Illustris-1-Subbox2","Illustris-1 subbox 2",                    3972, True),
    ("Illustris-1-Subbox3","Illustris-1 subbox 3",                    3970, True),
    ("Illustris-2-Subbox0","Illustris-2 subbox 0",                    2265, True),
    ("Illustris-2-Subbox1","Illustris-2 subbox 1",                    2265, True),
    ("Illustris-2-Subbox2","Illustris-2 subbox 2",                    2264, True),
    ("Illustris-2-Subbox3","Illustris-2 subbox 3",                    2265, True),
    ("Illustris-3-Subbox0","Illustris-3 subbox 0",                    1426, True),
    ("Illustris-3-Subbox1","Illustris-3 subbox 1",                    1426, True),
    ("Illustris-3-Subbox2","Illustris-3 subbox 2",                    1426, True),
    ("Illustris-3-Subbox3","Illustris-3 subbox 3",                    1426, True),
]

# Keys in the simulation detail "files" dict that are handled specially
_SKIP_FILE_KEYS = {"lhalotree", "sublink", "offsets", "snapshots", "checksums"}

# Keys whose files stay under output/ (not postprocessing/)
_OUTPUT_FILE_KEYS = {"ics", "simulation"}

# Mapping from simulation detail "files" key to local filename (under output/)
_SINGLE_FILE_KEYS: dict[str, str] = {
    "ics": "snap_ics.hdf5",
    "simulation": "simulation.hdf5",
}

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


# ---------------------------------------------------------------------------
# Name classification helpers
# ---------------------------------------------------------------------------


def _is_subbox(name: str) -> bool:
    """True if *name* is a subbox simulation."""
    return bool(re.search(r"-Subbox\d+$", name))


def _subbox_parent(name: str) -> str | None:
    """Extract parent simulation name from a subbox name.

    >>> _subbox_parent("TNG50-1-Subbox0")  → "TNG50-1"
    >>> _subbox_parent("TNG50-1")          → None
    """
    m = re.match(r"^(.+)-Subbox\d+$", name)
    return m.group(1) if m else None


def _family_name(name: str) -> str:
    """Extract the family/base name by stripping known variant suffixes.

    >>> _family_name("TNG50-1-Dark")    → "TNG50-1"
    >>> _family_name("TNG50-1-Subbox0") → "TNG50-1"
    >>> _family_name("TNG50-1")         → "TNG50-1"
    """
    base = re.sub(r"-Subbox\d+$", "", name)
    if base.endswith("-Dark"):
        base = base[:-5]
    return base


def _sub_group(name: str) -> str:
    """Extract the sub-group name (box-size / project group).

    >>> _sub_group("TNG50-1")       → "TNG50"
    >>> _sub_group("TNG100-1-Dark") → "TNG100"
    >>> _sub_group("Illustris-1")   → "Illustris"
    >>> _sub_group("TNG-Cluster")   → "TNG-Cluster"
    """
    base = _family_name(name)
    if base.startswith("Illustris"):
        return "Illustris"
    if base.startswith("TNG-Cluster"):
        return "TNG-Cluster"
    m = re.match(r"^(TNG\d+)", base)
    if m:
        return m.group(1)
    return base


# ---------------------------------------------------------------------------
# API fetchers (one level at a time — each with offline + error fallback)
# ---------------------------------------------------------------------------


def _fetch_simulations() -> list[tuple[str, str, int, bool]]:
    """Fetch simulation list from the TNG API root.

    Returns list of (name, description, num_snapshots, is_subbox).
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
            "TNG API returned no simulation list. Using fallback list."
        )
        return list(_FALLBACK_SIMULATIONS)

    result: list[tuple[str, str, int, bool]] = []
    for s in sims:
        name = s.get("name", "")
        if not name:
            continue
        desc = s.get("description", s.get("title", ""))
        nsnap = s.get("num_snapshots", 100)
        is_sub = _is_subbox(name)
        result.append((name, desc, nsnap, is_sub))
    return result


def _fetch_simulation_detail(sim_name: str) -> dict:
    """Fetch full simulation detail from ``{BASE_URL}{sim_name}/``."""
    fallback: dict = {
        "description": sim_name,
        "num_snapshots": 100,
        "boxsize": 0.0,
        "cosmology": "unknown",
        "is_subbox": False,
        "child_simulations": [],
        "files": {},
        "has_lhalotree": False,
        "has_sublink": False,
    }

    if _is_offline():
        # Try to get num_snapshots from fallback list
        for fn, fd, fs, fb in _FALLBACK_SIMULATIONS:
            if fn == sim_name:
                fallback["num_snapshots"] = fs
                fallback["is_subbox"] = fb
                fallback["description"] = fd
                break
        return fallback

    client = _make_client()
    if client is None:
        return fallback

    try:
        resp = client.get(f"{TNG_API_BASE}{sim_name}/")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return fallback
    finally:
        client.close()


def _fetch_snapshots(sim_name: str) -> list[dict]:
    """Fetch snapshot list from ``{BASE_URL}{sim_name}/snapshots/``."""
    if _is_offline():
        detail = _fetch_simulation_detail(sim_name)
        nsnap = detail.get("num_snapshots", 100)
        return [{"number": i, "redshift": None} for i in range(nsnap)]

    client = _make_client()
    if client is None:
        detail = _fetch_simulation_detail(sim_name)
        nsnap = detail.get("num_snapshots", 100)
        return [{"number": i, "redshift": None} for i in range(nsnap)]

    try:
        resp = client.get(f"{TNG_API_BASE}{sim_name}/snapshots/")
        resp.raise_for_status()
        return resp.json()
    except Exception:
        detail = _fetch_simulation_detail(sim_name)
        nsnap = detail.get("num_snapshots", 100)
        return [{"number": i, "redshift": None} for i in range(nsnap)]
    finally:
        client.close()


def _fetch_file_list(url: str) -> list[str]:
    """Fetch list of file URLs from a TNG API directory endpoint.

    E.g. ``files/groupcat-99/`` → ``{"files": ["...0.hdf5", ...]}``
    """
    if _is_offline():
        return []

    client = _make_client()
    if client is None:
        return []

    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    finally:
        client.close()

    files = data.get("files", [])
    if isinstance(files, list):
        return [f for f in files if isinstance(f, str)]
    return []


# ---------------------------------------------------------------------------
# Tree builders — each returns a dict[str, SourceNode] of children
# ---------------------------------------------------------------------------

# -- snapshots ---------------------------------------------------------------


def _build_snapshot_file_children(
    sim_name: str, snap_num: int,
) -> dict[str, SourceNode]:
    """Build children for an individual snapshot: snapshot/ and groupcat/ file lists."""
    path_prefix = f"TNG/{_sub_group(sim_name)}/{sim_name}/snapshots/sn-{snap_num}"
    nnn = f"{snap_num:03d}"
    children: dict[str, SourceNode] = {}

    # --- snapshot files ---
    snap_url = f"{TNG_API_BASE}{sim_name}/files/snapshot-{snap_num}/"
    snap_files = _fetch_file_list(snap_url)
    snap_kids: dict[str, SourceNode] = {}
    for f_url in snap_files:
        fname = f_url.rstrip("/").rsplit("/", 1)[-1]
        snap_kids[fname] = SourceNode(
            name=fname,
            path=f"{path_prefix}/snapshot/{fname}",
            description=f"Snapshot {snap_num} chunk",
            node_type="dataset",
            url=f_url,
            children={},
            download_relpath=f"{sim_name}/output/snapdir_{nnn}/{fname}",
        )
    children["snapshot"] = SourceNode(
        name="snapshot",
        path=f"{path_prefix}/snapshot",
        description=f"Snapshot {snap_num} files ({len(snap_files)} chunks)",
        node_type="category",
        child_count=len(snap_files),
        children=snap_kids,
        download_relpath=f"{sim_name}/output/snapdir_{nnn}/",
    )

    # --- groupcat files ---
    gc_url = f"{TNG_API_BASE}{sim_name}/files/groupcat-{snap_num}/"
    gc_files = _fetch_file_list(gc_url)
    gc_kids: dict[str, SourceNode] = {}
    for f_url in gc_files:
        fname = f_url.rstrip("/").rsplit("/", 1)[-1]
        gc_kids[fname] = SourceNode(
            name=fname,
            path=f"{path_prefix}/groupcat/{fname}",
            description=f"Group catalog {snap_num} chunk",
            node_type="dataset",
            url=f_url,
            children={},
            download_relpath=f"{sim_name}/output/groups_{nnn}/{fname}",
        )
    children["groupcat"] = SourceNode(
        name="groupcat",
        path=f"{path_prefix}/groupcat",
        description=f"Group catalog {snap_num} files ({len(gc_files)} chunks)",
        node_type="category",
        child_count=len(gc_files),
        children=gc_kids,
        download_relpath=f"{sim_name}/output/groups_{nnn}/",
    )

    return children


def _build_snapshots_children(sim_name: str) -> dict[str, SourceNode]:
    """Build children for the snapshots/ category: one node per snapshot."""
    snap_list = _fetch_snapshots(sim_name)
    children: dict[str, SourceNode] = {}
    path_prefix = f"TNG/{_sub_group(sim_name)}/{sim_name}/snapshots"

    for snap in snap_list:
        num = snap.get("number", 0)
        redshift = snap.get("redshift")
        name = f"sn-{num}"
        desc_parts = [f"Snapshot {num}"]
        if redshift is not None:
            desc_parts.append(f"z={redshift:.3f}")
        desc = ", ".join(desc_parts)

        def _make_loader(sn: str = sim_name, n: int = num):
            def _load() -> dict[str, SourceNode]:
                return _build_snapshot_file_children(sn, n)
            return _load

        children[name] = SourceNode(
            name=name,
            path=f"{path_prefix}/{name}",
            description=desc,
            node_type="category",
            metadata={"snapshot_number": num, "redshift": redshift},
            child_count=2,  # snapshot + groupcat
            _loader=_make_loader(),
        )

    return children


# -- postprocessing ----------------------------------------------------------


def _build_file_list_children(
    list_url: str, sim_name: str, relpath_prefix: str,
) -> dict[str, SourceNode]:
    """Build dataset children from a file listing URL."""
    files = _fetch_file_list(list_url)
    children: dict[str, SourceNode] = {}
    for f_url in files:
        fname = f_url.rstrip("/").rsplit("/", 1)[-1]
        # Build a reasonable path — use the sim name + relpath
        safe_path = f"TNG/{_sub_group(sim_name)}/{sim_name}/{relpath_prefix.rstrip('/')}/{fname}"
        children[fname] = SourceNode(
            name=fname,
            path=safe_path,
            description="",
            node_type="dataset",
            url=f_url,
            children={},
            download_relpath=f"{relpath_prefix}{fname}",
        )
    return children


def _build_postprocessing_children(
    sim_name: str, files: dict,
) -> dict[str, SourceNode]:
    """Build postprocessing/ children: trees (LHaloTree, SubLink) + offsets."""
    path_prefix = f"TNG/{_sub_group(sim_name)}/{sim_name}/postprocessing"
    children: dict[str, SourceNode] = {}

    # --- trees/ ---
    tree_children: dict[str, SourceNode] = {}
    for tree_name, file_key in [("LHaloTree", "lhalotree"), ("SubLink", "sublink")]:
        tree_url = files.get(file_key)
        if not tree_url or not isinstance(tree_url, str):
            continue

        relpath = f"{sim_name}/postprocessing/trees/{tree_name}/"
        if tree_url.rstrip("/").endswith((".hdf5", ".hdf5")):
            # Single file
            fname = tree_url.rstrip("/").rsplit("/", 1)[-1]
            tree_children[tree_name] = SourceNode(
                name=fname,
                path=f"{path_prefix}/trees/{fname}",
                description=f"{tree_name} merger tree data",
                node_type="dataset",
                url=tree_url,
                children={},
                download_relpath=f"{relpath}{fname}",
            )
        else:
            # Directory — lazy load file list
            def _make_loader(u: str = tree_url, sn: str = sim_name, rp: str = relpath):
                def _load() -> dict[str, SourceNode]:
                    return _build_file_list_children(u, sn, rp)
                return _load

            tree_children[tree_name] = SourceNode(
                name=tree_name,
                path=f"{path_prefix}/trees/{tree_name}",
                description=f"{tree_name} merger tree files",
                node_type="category",
                child_count=0,
                _loader=_make_loader(),
                download_relpath=relpath,
            )

    if tree_children:
        children["trees"] = SourceNode(
            name="trees",
            path=f"{path_prefix}/trees",
            description="Merger tree data",
            node_type="group",
            child_count=len(tree_children),
            children=tree_children,
        )

    # --- offsets/ ---
    offsets_url = files.get("offsets")
    if offsets_url and isinstance(offsets_url, str):
        relpath = f"{sim_name}/postprocessing/offsets/"
        if offsets_url.rstrip("/").endswith((".hdf5", ".hdf5")):
            fname = offsets_url.rstrip("/").rsplit("/", 1)[-1]
            children["offsets"] = SourceNode(
                name=fname,
                path=f"{path_prefix}/offsets/{fname}",
                description="Snapshot offsets",
                node_type="dataset",
                url=offsets_url,
                children={},
                download_relpath=f"{relpath}{fname}",
            )
        else:
            # Directory listing
            def _make_offsets_loader(u: str = offsets_url, sn: str = sim_name, rp: str = relpath):
                def _load() -> dict[str, SourceNode]:
                    return _build_file_list_children(u, sn, rp)
                return _load

            children["offsets"] = SourceNode(
                name="offsets",
                path=f"{path_prefix}/offsets",
                description="Snapshot offset files",
                node_type="category",
                child_count=0,
                _loader=_make_offsets_loader(),
                download_relpath=relpath,
            )

    return children


# -- single files ------------------------------------------------------------


def _build_files_children(
    sim_name: str, files: dict,
) -> dict[str, SourceNode]:
    """Build files/ children: single HDF5 downloads (ics, simulation, ...)."""
    path_prefix = f"TNG/{_sub_group(sim_name)}/{sim_name}/files"
    children: dict[str, SourceNode] = {}

    for key, url in sorted(files.items()):
        if key in _SKIP_FILE_KEYS:
            continue
        if not isinstance(url, str):
            continue
        # Skip per-snapshot keys
        if re.match(r"^(snapshot|groupcat)-\d+$", key):
            continue
        # Skip subbox subhalo list keys
        if re.match(r"^subbox_subhalo_list_\d+$", key):
            continue

        # Determine local filename and relpath
        if key in _SINGLE_FILE_KEYS:
            fname = _SINGLE_FILE_KEYS[key]
            relpath = f"{sim_name}/output/{fname}"
        else:
            fname = url.rstrip("/").rsplit("/", 1)[-1] or key
            if url.rstrip("/").endswith((".hdf5", ".h5", ".HDF5")):
                # Single HDF5 → postprocessing/
                relpath = f"{sim_name}/postprocessing/{fname}"
            else:
                # Directory-like URL → postprocessing/<key>/
                relpath = f"{sim_name}/postprocessing/{key}/"

        if url.rstrip("/").endswith((".hdf5", ".h5", ".HDF5")):
            # Single file
            children[fname] = SourceNode(
                name=fname,
                path=f"{path_prefix}/{fname}",
                description=key,
                node_type="dataset",
                url=url,
                children={},
                download_relpath=relpath,
            )
        else:
            # Directory — lazy-load file list
            def _make_loader(u: str = url, sn: str = sim_name, rp: str = relpath):
                def _load() -> dict[str, SourceNode]:
                    return _build_file_list_children(u, sn, rp)
                return _load

            children[key] = SourceNode(
                name=key,
                path=f"{path_prefix}/{key}",
                description=f"{key} files",
                node_type="category",
                child_count=0,
                _loader=_make_loader(),
                download_relpath=relpath,
            )

    return children


# -- subboxes ----------------------------------------------------------------


def _build_subboxes_children(
    child_urls: list[str], parent_sim: str, auth: AuthConfig | None,
) -> dict[str, SourceNode]:
    """Build subboxes/ children from ``child_simulations`` API field."""
    children: dict[str, SourceNode] = {}
    for url in child_urls:
        sub_name = url.rstrip("/").rsplit("/", 1)[-1]
        if not sub_name:
            continue
        # Determine subbox number for download path
        sub_m = re.search(r"Subbox(\d+)$", sub_name)
        sub_num = sub_m.group(1) if sub_m else "0"
        sub_relpath = f"{parent_sim}/output/subbox{sub_num}/"

        node = _build_simulation_node(
            sub_name, auth, is_subbox=True, parent_sim=parent_sim,
        )
        # Override: subbox data goes under the parent sim's output dir
        node.download_relpath = sub_relpath
        children[sub_name] = node

    return children


# -- simulation node ---------------------------------------------------------


def _build_simulation_children(
    sim_name: str,
    detail: dict,
    child_urls: list[str],
    auth: AuthConfig | None,
    *,
    is_subbox: bool = False,
    parent_sim: str | None = None,
) -> dict[str, SourceNode]:
    """Build the top-level children for a simulation node:
    snapshots/, postprocessing/, files/, subboxes/.
    """
    path_prefix = f"TNG/{_sub_group(sim_name)}/{sim_name}"
    files = detail.get("files", {})
    nsnap = detail.get("num_snapshots", 100)
    children: dict[str, SourceNode] = {}

    # -- snapshots/ --
    def _load_snapshots() -> dict[str, SourceNode]:
        return _build_snapshots_children(sim_name)
    children["snapshots"] = SourceNode(
        name="snapshots",
        path=f"{path_prefix}/snapshots",
        description=f"{nsnap} snapshots",
        node_type="category",
        child_count=nsnap,
        _loader=_load_snapshots,
        auth=auth,
    )

    # -- postprocessing/ --
    def _load_postproc() -> dict[str, SourceNode]:
        return _build_postprocessing_children(sim_name, files)
    children["postprocessing"] = SourceNode(
        name="postprocessing",
        path=f"{path_prefix}/postprocessing",
        description="Merger trees & offset data",
        node_type="group",
        child_count=0,
        _loader=_load_postproc,
        auth=auth,
    )

    # -- files/ --
    def _load_files() -> dict[str, SourceNode]:
        return _build_files_children(sim_name, files)
    # Count approximate number of single-file entries
    n_files = sum(
        1 for k, v in files.items()
        if k not in _SKIP_FILE_KEYS
        and isinstance(v, str)
        and not re.match(r"^(snapshot|groupcat)-\d+$", k)
        and not re.match(r"^subbox_subhalo_list_\d+$", k)
    )
    children["files"] = SourceNode(
        name="files",
        path=f"{path_prefix}/files",
        description=f"{n_files} catalog(s) & postprocessing file(s)",
        node_type="group",
        child_count=n_files,
        _loader=_load_files,
        auth=auth,
    )

    # -- subboxes/ --
    if child_urls:
        base_name = parent_sim if is_subbox and parent_sim else sim_name

        def _load_subboxes() -> dict[str, SourceNode]:
            return _build_subboxes_children(child_urls, base_name, auth)
        children["subboxes"] = SourceNode(
            name="subboxes",
            path=f"{path_prefix}/subboxes",
            description=f"{len(child_urls)} subbox simulation(s)",
            node_type="group",
            child_count=len(child_urls),
            _loader=_load_subboxes,
            auth=auth,
        )

    # -- Dark variant (peer simulation, if not already a subbox/dark) --
    # Only the main simulation gets dark peers; subboxes and dark variants don't.
    if not is_subbox and not sim_name.endswith("-Dark"):
        dark_name = f"{sim_name}-Dark"
        # Check if this dark variant exists (in API or fallback)
        dark_exists = False
        for fn, fd, fs, fb in _FALLBACK_SIMULATIONS:
            if fn == dark_name and fb == False:
                dark_exists = True
                break
        if dark_exists or True:  # Always add — it will be lazily loaded
            children[dark_name] = _build_simulation_node(
                dark_name, auth, is_subbox=False,
            )

    return children


def _build_simulation_node(
    sim_name: str,
    auth: AuthConfig | None,
    *,
    is_subbox: bool = False,
    parent_sim: str | None = None,
) -> SourceNode:
    """Create a simulation SourceNode with lazy-loaded detail children."""
    detail = _fetch_simulation_detail(sim_name)
    nsnap = detail.get("num_snapshots", 100)
    box = detail.get("boxsize", 0.0)
    cosmo = detail.get("cosmology", "unknown")
    desc = detail.get("description", sim_name)
    child_urls = detail.get("child_simulations", [])
    if not isinstance(child_urls, list):
        child_urls = []
    files = detail.get("files", {})

    # Count non-file children: snapshots + postprocessing + files + subboxes + dark
    child_count = 4  # snapshots, postprocessing, files, subboxes (or fewer if none)
    if not child_urls:
        child_count -= 1
    if not is_subbox and not sim_name.endswith("-Dark"):
        child_count += 1  # Dark variant

    meta: dict[str, object] = {
        "boxsize": box,
        "cosmology": cosmo,
        "num_snapshots": nsnap,
        "is_subbox": is_subbox,
    }
    if is_subbox and parent_sim:
        meta["parent_simulation"] = parent_sim

    path_prefix = f"TNG/{_sub_group(sim_name)}/{sim_name}"

    def _load_children() -> dict[str, SourceNode]:
        return _build_simulation_children(
            sim_name, detail, child_urls, auth,
            is_subbox=is_subbox, parent_sim=parent_sim,
        )

    return SourceNode(
        name=sim_name,
        path=path_prefix,
        description=desc,
        node_type="simulation",
        child_count=child_count,
        metadata=meta,
        _loader=_load_children,
        auth=auth,
        base_url=f"{TNG_API_BASE}{sim_name}/",
    )


# -- sub-group & root --------------------------------------------------------


def _build_subgroup_children(
    sims: list[tuple[str, str, int, bool]],
    auth: AuthConfig | None,
) -> dict[str, SourceNode]:
    """Build children for a sub-group node: simulation families (non-subbox sims)."""
    # Group sims by family name (for dark variants under main sim)
    families: dict[str, list[tuple[str, str, int, bool]]] = defaultdict(list)
    for name, desc, nsnap, is_sub in sims:
        families[_family_name(name)].append((name, desc, nsnap, is_sub))

    children: dict[str, SourceNode] = {}
    for family, family_sims in sorted(families.items()):
        # Find the main simulation (non-dark, non-subbox)
        main_sim = None
        for name, desc, nsnap, is_sub in family_sims:
            if not is_sub and not name.endswith("-Dark"):
                main_sim = (name, desc, nsnap, is_sub)
                break

        if main_sim is None:
            # Fallback: use first non-subbox
            for name, desc, nsnap, is_sub in family_sims:
                if not is_sub:
                    main_sim = (name, desc, nsnap, is_sub)
                    break

        if main_sim is None:
            continue

        name, desc, nsnap, is_sub = main_sim
        children[name] = _build_simulation_node(name, auth)

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
    return f"{base} — {count} resolution level(s)"


def _build_tng_children(auth: AuthConfig | None) -> dict[str, SourceNode]:
    """Build the top-level TNG children: sub-groups (TNG50, TNG100, ...)."""
    sims = _fetch_simulations()

    # Group by sub_group (box size / project)
    groups: dict[str, list[tuple[str, str, int, bool]]] = defaultdict(list)
    for name, desc, nsnap, is_sub in sims:
        groups[_sub_group(name)].append((name, desc, nsnap, is_sub))

    children: dict[str, SourceNode] = {}
    for group_name, group_sims in sorted(groups.items()):
        # Count non-subbox sims for the top-level count
        top_level = [(n, d, s, b) for n, d, s, b in group_sims if not b]
        # Count unique families
        family_set = {_family_name(n) for n, d, s, b in top_level}
        group_desc = _describe_sub_group(group_name, len(family_set))
        children[group_name] = SourceNode(
            name=group_name,
            path=f"TNG/{group_name}",
            description=group_desc,
            node_type="group",
            child_count=len(family_set),
            _loader=lambda g=group_sims, a=auth: _build_subgroup_children(g, a),
            auth=auth,
        )
    return children


# ---------------------------------------------------------------------------
# Public API: build the TNG root node
# ---------------------------------------------------------------------------


def build_tng_root() -> SourceNode:
    """Return the TNG root SourceNode.

    Children (sub-groups) are loaded lazily via the TNG API.
    """
    auth = _make_auth()

    # Count total simulations for the root description
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
