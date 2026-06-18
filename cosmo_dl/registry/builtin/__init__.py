"""Built-in simulation source definitions."""
from cosmo_dl.registry.source import SourceNode, SimulationSource
from cosmo_dl.registry.builtin.fire import build_fire2_root
from cosmo_dl.registry.builtin.auriga import build_auriga_root
from cosmo_dl.registry.builtin.tng import build_tng_root


def get_builtin_roots() -> list[SourceNode]:
    """Return root nodes for all built-in simulation sources.

    Each root is a :class:`SourceNode` whose children may be loaded lazily.
    """
    roots: list[SourceNode] = []

    # FIRE-2: native tree with lazy HTTP directory scraping (no API key needed)
    roots.append(build_fire2_root())

    # Auriga: native tree with Globus OAuth2 authentication
    roots.append(build_auriga_root())

    # TNG: native tree with lazy API loading
    roots.append(build_tng_root())

    return roots


def get_builtin_sources() -> list[SimulationSource]:
    """Return legacy SimulationSource objects (backward compat).

    All built-in sources have been migrated to the native ``SourceNode``
    tree — use ``get_builtin_roots()`` instead.  This function returns
    an empty list.
    """
    return []
