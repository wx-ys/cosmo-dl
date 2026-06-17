"""Registry class for managing simulation sources as a hierarchical tree."""
from __future__ import annotations

from cosmo_dl.registry.source import SourceNode, SimulationSource
from cosmo_dl.registry.builtin import get_builtin_roots
from cosmo_dl.registry.loader import load_sources_from_yaml


class Registry:
    """Central registry of simulation data sources.

    Sources are organised as a tree of :class:`SourceNode` objects.
    Nodes are loaded lazily — API calls only happen when you navigate
    into a node for the first time.
    """

    def __init__(self, user_config_path: str | None = None):
        self._roots: dict[str, SourceNode] = {}

        # Load built-in root nodes
        for root in get_builtin_roots():
            self._roots[root.name] = root

        # Load user-defined sources and convert to nodes
        import os
        if user_config_path is None:
            user_config_path = os.path.expanduser("~/.config/cosmo-dl/sources.yaml")
        for src in load_sources_from_yaml(user_config_path):
            node = src.to_node()
            self._roots[node.name] = node

    # ------------------------------------------------------------------
    # Tree navigation
    # ------------------------------------------------------------------

    @property
    def roots(self) -> dict[str, SourceNode]:
        """Return the top-level root nodes."""
        return self._roots

    def get_node(self, path: str) -> SourceNode | None:
        """Navigate to a node by its path (e.g. ``"TNG/TNG50/TNG50-1"``).

        Path segments are separated by ``/``.  Each segment triggers
        lazy loading if needed.
        """
        if not path:
            return None
        parts = path.strip("/").split("/", 1)
        root_name = parts[0]
        root = self._roots.get(root_name)
        if root is None:
            return None
        if len(parts) == 1:
            return root
        return root.navigate(parts[1])

    # ------------------------------------------------------------------
    # Legacy API (backward compat)
    # ------------------------------------------------------------------

    def list(self) -> list[str]:
        """Return sorted names of all root nodes."""
        return sorted(self._roots.keys())

    def list_by_group(self) -> dict[str, list[str]]:
        """Return root nodes grouped (all roots are top-level groups)."""
        return {"Simulations": self.list()}

    def get(self, name: str) -> SimulationSource | None:
        """Legacy: return a SimulationSource by name, or None."""
        node = self._roots.get(name)
        if node is None:
            return None
        # Try to convert back (lossy for native trees)
        from cosmo_dl.registry.source import DatasetInfo
        datasets: dict[str, DatasetInfo] = {}
        for child in node.list_children().values():
            datasets[child.name] = DatasetInfo(
                path=child.name + "/",
                description=child.description,
            )
        return SimulationSource(
            name=node.name,
            description=node.description,
            base_url=node.base_url or "",
            auth=node.auth,
            datasets=datasets,
        )

    def resolve(self, target: str) -> list[str]:
        """Resolve *target* into download URLs.

        Supports:
        - Raw URLs (passthrough)
        - Tree paths: ``TNG/TNG50/TNG50-1/groupcat/groupcat-99``
        - Legacy: ``SourceName/dataset``
        """
        if target.startswith(("http://", "https://")):
            return [target]

        # Try tree navigation
        node = self.get_node(target)
        if node is not None:
            return node.resolve()

        # Legacy fallback
        if "/" in target:
            source_name, dataset = target.split("/", 1)
            src = self._roots.get(source_name)
            if src is not None and hasattr(src, 'base_url') and src.base_url:
                child = src.get_child(dataset)
                if child is not None:
                    return child.resolve()
                raise KeyError(f"Unknown dataset: {dataset!r}")
            raise ValueError(f"Unknown source: {source_name!r}")

        raise ValueError(f"Unknown target: {target!r}")
