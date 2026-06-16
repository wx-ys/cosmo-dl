"""FIRE simulation public release data source."""
from cosmo_dl.registry.source import SimulationSource, DatasetInfo

FIRE_SOURCE = SimulationSource(
    name="FIRE",
    description="FIRE-2 public release (Flatiron Institute)",
    base_url="https://users.flatironinstitute.org/~mgrudic/fire2_public_release/",
    structure="mirror",
    group="FIRE",
    datasets={
        "m11i_res7100": DatasetInfo(
            path="core/m11i_res7100/output/",
            description="M11i galaxy, resolution 7100, full output",
        ),
        "m12i_res7100": DatasetInfo(
            path="core/m12i_res7100/output/",
            description="M12i galaxy, resolution 7100, full output",
        ),
    },
)
