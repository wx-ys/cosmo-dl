"""Built-in simulation source definitions."""
from cosmo_dl.registry.source import SourceNode, SimulationSource
from cosmo_dl.registry.builtin.fire import FIRE_SOURCE
from cosmo_dl.registry.builtin.auriga import AURIGA_SOURCE
from cosmo_dl.registry.builtin.tng import build_tng_root


def get_builtin_roots() -> list[SourceNode]:
    """Return root nodes for all built-in simulation sources.

    Each root is a :class:`SourceNode` whose children may be loaded lazily.
    Legacy :class:`SimulationSource` objects are converted via ``to_node()``.
    """
    roots: list[SourceNode] = []

    # Legacy sources → convert to tree
    roots.append(FIRE_SOURCE.to_node())
    roots.append(AURIGA_SOURCE.to_node())

    # TNG: native tree with lazy loading
    roots.append(build_tng_root())

    return roots


def get_builtin_sources() -> list[SimulationSource]:
    """Return legacy SimulationSource objects (backward compat)."""
    return [FIRE_SOURCE, AURIGA_SOURCE]
