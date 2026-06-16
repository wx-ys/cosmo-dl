"""Built-in simulation source definitions."""
from cosmo_dl.registry.source import SimulationSource
from cosmo_dl.registry.builtin.fire import FIRE_SOURCE
from cosmo_dl.registry.builtin.auriga import AURIGA_SOURCE
from cosmo_dl.registry.builtin.tng import TNG50_SOURCE, TNG100_SOURCE, TNG300_SOURCE

def get_builtin_sources() -> list[SimulationSource]:
    return [FIRE_SOURCE, AURIGA_SOURCE, TNG50_SOURCE, TNG100_SOURCE, TNG300_SOURCE]
