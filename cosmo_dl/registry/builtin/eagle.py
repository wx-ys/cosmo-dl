"""EAGLE simulation data source — known simulation tree with download API.

The EAGLE (Evolution and Assembly of GaLaxies and their Environments)
simulations are a suite of cosmological hydrodynamical simulations
performed with a modified version of the GADGET-3 code.

The EAGLE data server uses a query/download API (not directory listings).
Simulation metadata is hardcoded from the official EAGLE database
documentation.  Each snapshot is downloaded as a tar file via::

    /download?run=<run>&snapnum=<N>

Tree structure::

    EAGLE/                              root group
      Fiducial_models/                  schema group
        RefL0100N1504/                  simulation (29 snapshots, z=20→0)
          snapshots/                    snapshot list
            sn-00/                      dataset (z=20.00)
            sn-01/                      dataset (z=15.13)
            ...
            sn-28/                      dataset (z=0.00)
      Physics_vars/                     schema group
        FBconstL0050N0752/              simulation (29 snapshots)
          ...
      DMONLY/                           schema group
        L0100N1504/                     DM-only simulation (no snapshots)
          (no children)

HTTP Basic Authentication is required.  Credentials are read from
environment variables (``EAGLE_USERNAME``, ``EAGLE_PASSWORD``),
``.env`` files, or the TOML config file (``eagle_username``,
``eagle_password``).
"""

from __future__ import annotations

import logging

from cosmo_dl.config import get as config_get
from cosmo_dl.engine.types import AuthConfig
from cosmo_dl.registry.source import SourceNode

logger = logging.getLogger(__name__)

EAGLE_BASE_URL = "https://dataweb.cosma.dur.ac.uk:8443/eagle-snapshots"

# ---------------------------------------------------------------------------
# Snapshot redshift tables
# ---------------------------------------------------------------------------

# Standard 29-snapshot sequence (snapnum → redshift), for most simulations.
_STANDARD_REDSHIFTS: dict[int, float] = {
    28: 0.00,
    27: 0.10,
    26: 0.18,
    25: 0.27,
    24: 0.37,
    23: 0.50,
    22: 0.62,
    21: 0.74,
    20: 0.87,
    19: 1.00,
    18: 1.26,
    17: 1.49,
    16: 1.74,
    15: 2.01,
    14: 2.24,
    13: 2.48,
    12: 3.02,
    11: 3.53,
    10: 3.98,
    9: 4.49,
    8: 5.04,
    7: 5.49,
    6: 5.97,
    5: 7.05,
    4: 8.07,
    3: 8.99,
    2: 9.99,
    1: 15.13,
    0: 20.00,
}

# Variable-IMF runs (HiM, LoM) have only 11 snapshots (0–10).
_VARIMF_REDSHIFTS: dict[int, float] = {
    10: 0.00,
    9: 0.10,
    8: 0.18,
    7: 0.27,
    6: 0.50,
    5: 1.00,
    4: 1.49,
    3: 2.01,
    2: 3.02,
    1: 3.98,
    0: 5.97,
}

# ---------------------------------------------------------------------------
# Simulation registry
# ---------------------------------------------------------------------------
# Each entry: (run, schema, box, particles, notes, num_snapshots, has_snapshots)

_SIMULATIONS: list[tuple[str, str, str, str, str, int, bool]] = [
    # -- Small test run -------------------------------------------------------
    (
        "RefL0012N0188",
        "Fiducial_models",
        "12.5 Mpc",
        "188³",
        "Tiny volume reference model",
        29,
        True,
    ),
    # -- Schaye et al. (2015) — Fiducial_models -------------------------------
    (
        "RefL0100N1504",
        "Fiducial_models",
        "100 Mpc",
        "1504³",
        "Large volume reference model",
        29,
        True,
    ),
    (
        "RefL0050N0752",
        "Fiducial_models",
        "50 Mpc",
        "752³",
        "Medium volume reference model",
        29,
        True,
    ),
    (
        "RefL0025N0376",
        "Fiducial_models",
        "25 Mpc",
        "376³",
        "Small volume reference model",
        29,
        True,
    ),
    (
        "RefL0025N0752",
        "Fiducial_models",
        "25 Mpc",
        "752³",
        "High resolution reference model",
        29,
        True,
    ),
    (
        "RecalL0025N0752",
        "Fiducial_models",
        "25 Mpc",
        "752³",
        "High resolution recalibrated model",
        29,
        True,
    ),
    (
        "AGNdT9L0050N0752",
        "Fiducial_models",
        "50 Mpc",
        "752³",
        "Medium volume with adjusted AGN heating",
        29,
        True,
    ),
    # -- Crain et al. (2015) — Physics_vars -----------------------------------
    (
        "FBconstL0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "FBconst in Crain+2015 table 1",
        29,
        True,
    ),
    ("FBsigmaL0050N0752", "Physics_vars", "50 Mpc", "752³", "FBσ in Crain+2015 table 1", 29, True),
    ("FBZL0050N0752", "Physics_vars", "50 Mpc", "752³", "FBZ in Crain+2015 table 1", 29, True),
    ("eos1L0025N0376", "Physics_vars", "25 Mpc", "376³", "eos1 in Crain+2015 table 1", 29, True),
    ("eos53L0025N0376", "Physics_vars", "25 Mpc", "376³", "eos5/3 in Crain+2015 table 1", 29, True),
    (
        "FixedSfThreshL0025N0376",
        "Physics_vars",
        "25 Mpc",
        "376³",
        "FixedSfThresh in Crain+2015 table 1",
        29,
        True,
    ),
    (
        "WeakFBL0025N0376",
        "Physics_vars",
        "25 Mpc",
        "376³",
        "WeakFB in Crain+2015 table 1",
        29,
        True,
    ),
    (
        "StrongFBL0025N0376",
        "Physics_vars",
        "25 Mpc",
        "376³",
        "StrongFB in Crain+2015 table 1",
        29,
        True,
    ),
    (
        "ViscLoL0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "ViscLo in Crain+2015 table 1",
        29,
        True,
    ),
    (
        "ViscHiL0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "ViscHi in Crain+2015 table 1",
        29,
        True,
    ),
    (
        "C15AGNdT8L0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "AGNdT8 in Crain+2015 table 1",
        29,
        True,
    ),
    (
        "C15AGNdT9L0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "AGNdT9 in Crain+2015 table 1",
        29,
        True,
    ),
    # -- Barber et al. (2018) — Physics_vars ----------------------------------
    (
        "HiML0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "IMF top-heavy at high birth pressure — 11 snapshots",
        11,
        True,
    ),
    (
        "LoML0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "IMF bottom-heavy at high birth pressure — 11 snapshots",
        11,
        True,
    ),
    # -- No black holes — Physics_vars ----------------------------------------
    (
        "NoAGNL0025N0376",
        "Physics_vars",
        "25 Mpc",
        "376³",
        "Small volume with no black holes",
        29,
        True,
    ),
    (
        "NoAGNL0050N0752",
        "Physics_vars",
        "50 Mpc",
        "752³",
        "Medium volume with no black holes",
        29,
        True,
    ),
    # -- Dark matter only — DMONLY --------------------------------------------
    ("L0025N0376", "DMONLY", "25 Mpc", "376³", "Small volume DMONLY model", 0, False),
    ("L0025N0752", "DMONLY", "25 Mpc", "752³", "Small volume DMONLY at high resolution", 0, False),
    ("L0100N1504", "DMONLY", "100 Mpc", "1504³", "Large volume DMONLY model", 0, False),
]

# Schemas in display order, with descriptions
_SCHEMA_ORDER = [
    ("Fiducial_models", "Reference & recalibrated models (Schaye+2015, Crain+2015)"),
    ("Physics_vars", "Physics variation models (Crain+2015, Barber+2018)"),
    ("DMONLY", "Dark-matter-only models"),
]

# Build lookup: run → (schema, box, particles, notes, n_snap, has_snaps)
_RUN_INFO: dict[str, tuple[str, str, str, str, int, bool]] = {}
for _s in _SIMULATIONS:
    _RUN_INFO[_s[0]] = (_s[1], _s[2], _s[3], _s[4], _s[5], _s[6])


# ---------------------------------------------------------------------------
# Tree builders
# ---------------------------------------------------------------------------


def _build_snapshot_children(
    sim_name: str,
    path_prefix: str,
    num_snapshots: int,
) -> dict[str, SourceNode]:
    """Build snapshot child nodes for a simulation.

    Each snapshot is a ``dataset`` node whose URL points to the EAGLE
    download endpoint.  The server returns a tar file (via
    ``Content-Disposition``).
    """
    is_varimf = sim_name in ("HiML0050N0752", "LoML0050N0752")
    redshift_map = _VARIMF_REDSHIFTS if is_varimf else _STANDARD_REDSHIFTS

    children: dict[str, SourceNode] = {}
    for snap_num in range(num_snapshots):
        z = redshift_map.get(snap_num)
        z_str = f"z={z:.2f}" if z is not None else f"snapshot {snap_num}"
        name = f"sn-{snap_num:02d}"

        download_url = f"{EAGLE_BASE_URL}/download?run={sim_name}&snapnum={snap_num}"

        children[name] = SourceNode(
            name=name,
            path=f"{path_prefix}/{name}",
            description=f"Snapshot {snap_num} ({z_str})",
            node_type="dataset",
            url=download_url,
            children={},
            metadata={"snapshot_number": snap_num, "redshift": z},
        )

    return children


def _build_simulation_children(
    sim_name: str,
    path_prefix: str,
    num_snapshots: int,
) -> dict[str, SourceNode]:
    """Build children for a simulation node (snapshots/ category)."""
    children: dict[str, SourceNode] = {}

    if num_snapshots > 0:

        def _load_snapshots() -> dict[str, SourceNode]:
            return _build_snapshot_children(sim_name, f"{path_prefix}/snapshots", num_snapshots)

        children["snapshots"] = SourceNode(
            name="snapshots",
            path=f"{path_prefix}/snapshots",
            description=f"{num_snapshots} snapshots",
            node_type="category",
            child_count=num_snapshots,
            _loader=_load_snapshots,
        )

    return children


def _build_schema_children(schema: str) -> dict[str, SourceNode]:
    """Build children for a schema group (simulation nodes)."""
    children: dict[str, SourceNode] = {}

    for run, s, box, particles, notes, n_snap, has_snaps in _SIMULATIONS:
        if s != schema:
            continue

        desc_parts = [f"{box}, {particles} particles"]
        if notes:
            desc_parts.append(notes)
        if n_snap > 0:
            desc_parts.append(f"{n_snap} snapshots")
        elif not has_snaps:
            desc_parts.append("no public snapshots")

        desc = " — ".join(desc_parts)
        sim_path = f"EAGLE/{schema}/{run}"

        children[run] = SourceNode(
            name=run,
            path=sim_path,
            description=desc,
            node_type="simulation",
            child_count=1 if n_snap > 0 else 0,
            metadata={
                "box_size": box,
                "particles": particles,
                "num_snapshots": n_snap,
                "schema": schema,
            },
            _loader=lambda r=run, sp=sim_path, ns=n_snap: _build_simulation_children(r, sp, ns),  # type: ignore[misc]
        )

    return children


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _make_eagle_auth() -> AuthConfig | None:
    """Return an ``AuthConfig`` for EAGLE Basic Auth, or ``None``.

    Reads credentials from config (env vars, ``.env`` files, or TOML).
    """
    username = config_get("eagle_username")
    password = config_get("eagle_password")
    if username and password:
        return AuthConfig(type="basic", username=username, password=password)
    return None


def build_eagle_root() -> SourceNode:
    """Return the EAGLE root ``SourceNode``.

    Children are organised by database schema (``Fiducial_models``,
    ``Physics_vars``, ``DMONLY``), with simulations underneath.
    Snapshots are loaded lazily.

    HTTP Basic Authentication is required — set ``eagle_username`` and
    ``eagle_password`` via environment variables, ``.env`` files, or
    the TOML config file.

    Returns
    -------
    SourceNode
        Root node of the EAGLE source tree.  ``node_type`` is ``"group"``,
        ``name`` is ``"EAGLE"``.
    """
    total_sims = len(_SIMULATIONS)
    auth = _make_eagle_auth()

    def _load_root_children() -> dict[str, SourceNode]:
        children: dict[str, SourceNode] = {}
        for schema, desc in _SCHEMA_ORDER:
            # Count simulations in this schema
            schema_sims = [s for s in _SIMULATIONS if s[1] == schema]
            children[schema] = SourceNode(
                name=schema,
                path=f"EAGLE/{schema}",
                description=desc,
                node_type="group",
                child_count=len(schema_sims),
                _loader=lambda sc=schema: _build_schema_children(sc),  # type: ignore[misc]
            )
        return children

    return SourceNode(
        name="EAGLE",
        path="EAGLE",
        description=f"EAGLE simulations (Virgo Consortium) — {total_sims} simulation(s)",
        node_type="group",
        child_count=len(_SCHEMA_ORDER),
        _loader=_load_root_children,
        base_url=EAGLE_BASE_URL,
        auth=auth,
    )
