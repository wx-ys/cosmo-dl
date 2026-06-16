"""Auriga simulation data source."""
from cosmo_dl.registry.source import SimulationSource, DatasetInfo

_AURIGA_HALOS = {}
for _n in range(1, 31):
    _AURIGA_HALOS[f"halo-{_n}"] = DatasetInfo(
        path=f"halo_{_n}/",
        description=f"Auriga Halo {_n}, level 4, snapshot 127",
    )

AURIGA_SOURCE = SimulationSource(
    name="Auriga",
    description="Auriga simulation, halos 1-30, level 4",
    base_url="https://g-5a93c7.140599.5898.data.globus.org/level4/Original/",
    structure="pattern",
    datasets=_AURIGA_HALOS,
)
