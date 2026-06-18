"""Built-in simulation source definitions."""
from cosmo_dl.registry.source import SourceNode, SimulationSource
from cosmo_dl.registry.builtin.fire import build_fire2_root
from cosmo_dl.registry.builtin.auriga import AURIGA_SOURCE
from cosmo_dl.registry.builtin.tng import build_tng_root


def get_builtin_roots() -> list[SourceNode]:
    """Return root nodes for all built-in simulation sources.

    Each root is a :class:`SourceNode` whose children may be loaded lazily.
    Legacy :class:`SimulationSource` objects are converted via ``to_node()``.
    """
    roots: list[SourceNode] = []

    # FIRE-2: native tree with lazy HTTP directory scraping (no API key needed)
    roots.append(build_fire2_root())

    # Auriga: legacy source → convert to tree
    roots.append(AURIGA_SOURCE.to_node())

    # TNG: native tree with lazy API loading
    roots.append(build_tng_root())

    return roots


def get_builtin_sources() -> list[SimulationSource]:
    """Return legacy SimulationSource objects (backward compat).

    Only sources that were originally defined as ``SimulationSource``
    are included.  Sources that have been migrated to the native
    ``SourceNode`` tree (FIRE-2, TNG) are not included here — use
    ``get_builtin_roots()`` instead.
    """
    return [AURIGA_SOURCE]
