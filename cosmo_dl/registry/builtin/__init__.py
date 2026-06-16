"""Built-in simulation source definitions."""
from cosmo_dl.registry.source import SimulationSource
from cosmo_dl.registry.builtin.fire import FIRE_SOURCE
from cosmo_dl.registry.builtin.auriga import AURIGA_SOURCE
from cosmo_dl.registry.builtin.tng import get_tng_sources


def get_builtin_sources() -> list[SimulationSource]:
    """Return all built-in simulation sources.

    TNG sources are auto-discovered from the TNG API (with fallback
    to a hard-coded list when the API is unreachable).
    """
    sources: list[SimulationSource] = [FIRE_SOURCE, AURIGA_SOURCE]

    # Discover TNG simulations from the API
    tng_sources = get_tng_sources()
    sources.extend(tng_sources)

    return sources

