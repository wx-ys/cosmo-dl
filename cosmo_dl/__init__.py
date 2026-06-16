"""cosmo-dl: Download cosmological simulation data."""

__version__ = "0.1.0"

from cosmo_dl.api import download, explore, list_sources
from cosmo_dl.engine.types import DownloadResult, FileEntry, AuthConfig
from cosmo_dl.registry.source import SimulationSource, DatasetInfo

__all__ = [
    "__version__",
    "download",
    "explore",
    "list_sources",
    "DownloadResult",
    "FileEntry",
    "AuthConfig",
    "SimulationSource",
    "DatasetInfo",
]
