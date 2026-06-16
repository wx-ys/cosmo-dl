"""IllustrisTNG simulation data source.

Requires an API key from https://www.tng-project.org (free registration).
Set the key via environment variable ``TNG_API_KEY`` or in the auth config.
"""
from cosmo_dl.engine.types import AuthConfig
from cosmo_dl.registry.source import SimulationSource, DatasetInfo


def _make_auth() -> AuthConfig | None:
    """Create an AuthConfig that reads the TNG API key from the environment."""
    import os
    api_key = os.environ.get("TNG_API_KEY", "")
    if api_key:
        return AuthConfig(type="api-key", token=api_key)
    # Without an API key, requests may be limited or fail.
    # The user can also provide the key via YAML config.
    return None


def _make_tng_source(name: str, description: str) -> SimulationSource:
    """Build a TNG simulation source with standard datasets.

    Each source exposes:
    - ``groupcat-{N}`` — group catalog for snapshot N (N=0..99)
    - ``snapshot-{N}`` — snapshot data for snapshot N (N=0..99)
    """
    base_url = f"http://www.tng-project.org/api/{name}/"

    datasets: dict[str, DatasetInfo] = {}

    # Group catalogs: 0-99
    for i in range(100):
        datasets[f"groupcat-{i}"] = DatasetInfo(
            path=f"files/groupcat-{i}/",
            description=f"{name} group catalog, snapshot {i}",
        )

    # Snapshots: key snapshots (full particle data is very large)
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
    )


# Three TNG simulation boxes
TNG50_SOURCE = _make_tng_source(
    "TNG50-1",
    "IllustrisTNG 50 Mpc/h box, full physics (TNG50-1)",
)
TNG100_SOURCE = _make_tng_source(
    "TNG100-1",
    "IllustrisTNG 100 Mpc/h box, full physics (TNG100-1)",
)
TNG300_SOURCE = _make_tng_source(
    "TNG300-1",
    "IllustrisTNG 300 Mpc/h box, full physics (TNG300-1)",
)
