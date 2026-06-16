"""IllustrisTNG simulation data source.

Requires an API key from https://www.tng-project.org (free registration).

Set the key using any of these methods (highest priority first):

1. Environment variable: ``export TNG_API_KEY="your-key"``
2. ``.env`` file (``./.env`` or ``~/.config/cosmo-dl/.env``): ``TNG_API_KEY=your-key``
3. CLI command: ``cosmo-dl config set tng_api_key "your-key"``
"""
from cosmo_dl.config import get as config_get
from cosmo_dl.engine.types import AuthConfig
from cosmo_dl.registry.source import SimulationSource, DatasetInfo


def _make_auth() -> AuthConfig | None:
    """Resolve the TNG API key from all configured sources."""
    api_key = config_get("tng_api_key")
    if api_key:
        return AuthConfig(type="api-key", token=api_key)
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
