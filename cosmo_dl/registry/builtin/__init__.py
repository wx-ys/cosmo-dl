"""Built-in simulation source definitions."""
from cosmo_dl.registry.source import SimulationSource
from cosmo_dl.registry.builtin.fire import FIRE_SOURCE
from cosmo_dl.registry.builtin.auriga import AURIGA_SOURCE

def get_builtin_sources() -> list[SimulationSource]:
    return [FIRE_SOURCE, AURIGA_SOURCE]
