"""Registry class for managing simulation sources and resolving datasets."""
import os
from cosmo_dl.registry.source import SimulationSource
from cosmo_dl.registry.builtin import get_builtin_sources
from cosmo_dl.registry.loader import load_sources_from_yaml


class Registry:
    """Central registry of simulation data sources.

    Manages built-in sources, user-defined YAML sources, and
    programmatically registered sources.  Resolves human-readable
    ``Source/dataset`` identifiers into concrete download URLs.
    """

    def __init__(self, user_config_path: str | None = None):
        """Create a Registry, loading built-in and user-defined sources.

        Parameters
        ----------
        user_config_path:
            Path to a YAML file with user-defined sources.  Defaults to
            ``~/.config/cosmo-dl/sources.yaml``.
        """
        self._sources: dict[str, SimulationSource] = {}

        # Load built-in sources.
        for src in get_builtin_sources():
            self._sources[src.name] = src

        # Load user-defined sources.
        if user_config_path is None:
            user_config_path = os.path.expanduser("~/.config/cosmo-dl/sources.yaml")
        for src in load_sources_from_yaml(user_config_path):
            self._sources[src.name] = src

    def list(self) -> list[str]:
        """Return a sorted list of registered source names."""
        return sorted(self._sources.keys())

    def list_by_group(self) -> dict[str, list[str]]:
        """Return sources grouped by their ``group`` field.

        Sources without a group are placed under ``"Other"``.

        Returns
        -------
        dict[str, list[str]]
            Group name → sorted list of source names.
        """
        groups: dict[str, list[str]] = {}
        for name, src in self._sources.items():
            group = src.group or "Other"
            groups.setdefault(group, []).append(name)
        # Sort each group's list
        for g in groups:
            groups[g].sort()
        return dict(sorted(groups.items()))

    def get(self, name: str) -> SimulationSource | None:
        """Return the :class:`SimulationSource` for *name*, or ``None``."""
        return self._sources.get(name)

    def register(self, source: SimulationSource) -> None:
        """Register *source* programmatically."""
        self._sources[source.name] = source

    def refresh_tng(self) -> int:
        """Re-discover TNG simulations from the API and update the registry.

        Returns the number of TNG sources registered.
        """
        from cosmo_dl.registry.builtin.tng import get_tng_sources

        # Remove existing TNG sources
        tng_names = [n for n, s in self._sources.items() if s.group == "TNG"]
        for name in tng_names:
            del self._sources[name]

        # Re-discover
        count = 0
        for src in get_tng_sources():
            self._sources[src.name] = src
            count += 1
        return count

    def resolve(self, target: str) -> list[str]:
        """Resolve *target* into a list of concrete URLs.

        Parameters
        ----------
        target:
            One of:
            - A raw URL (``http://`` or ``https://``) -- returned as-is.
            - A ``Source`` name (no ``/``) -- returns ``[source.base_url]``.
            - A ``Source/dataset`` identifier -- looks up the source and
              resolves the dataset name through
              :meth:`SimulationSource.resolve`.

        Returns
        -------
        list[str]
            Concrete HTTPS URLs suitable for downloading.

        Raises
        ------
        ValueError
            If the source portion of *target* is unknown.
        KeyError
            If the dataset portion is unknown for the given source.
        """
        if target.startswith(("http://", "https://")):
            return [target]

        if "/" not in target:
            # Just a source name -- return its base URL.
            src = self._sources.get(target)
            if src is None:
                raise ValueError(f"Unknown source: {target!r}")
            return [src.base_url]

        # Source/dataset form.
        source_name, dataset_name = target.split("/", 1)

        src = self._sources.get(source_name)
        if src is None:
            raise ValueError(f"Unknown source: {source_name!r}")

        return src.resolve(dataset_name)
