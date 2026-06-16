"""Registry source types — SourceNode tree and legacy SimulationSource."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


# ---------------------------------------------------------------------------
# SourceNode — hierarchical source tree
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SourceNode:
    """A node in the simulation source tree.

    Like a directory in a filesystem: it has a name, a description,
    and (optionally lazily-loaded) children.  Leaf nodes carry a
    ``url`` and can be downloaded.
    """

    name: str
    path: str
    description: str = ""
    node_type: Literal["group", "category", "dataset"] = "group"

    # Children — None means "not loaded yet"
    children: dict[str, SourceNode] | None = None
    child_count: int = 0
    _loader: Callable[[], dict[str, SourceNode]] | None = field(
        default=None, repr=False, compare=False
    )

    # Auth inherited from ancestors
    auth: object | None = field(default=None, repr=False, compare=False)

    # Only for dataset nodes
    url: str | None = None
    base_url: str | None = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_loaded(self) -> bool:
        """True if children have been loaded."""
        return self.children is not None

    def list_children(self) -> dict[str, SourceNode]:
        """Return children, loading them lazily if needed."""
        if self.children is None:
            if self._loader is not None:
                self.children = self._loader()
            else:
                self.children = {}
        return self.children

    def get_child(self, name: str) -> SourceNode | None:
        """Get a direct child by name, loading lazily."""
        return self.list_children().get(name)

    def navigate(self, path: str) -> SourceNode | None:
        """Walk down the tree following slash-separated *path*.

        Each segment loads lazily.  Returns the target node or ``None``
        if any segment is not found.
        """
        if not path:
            return self
        node = self
        for segment in path.strip("/").split("/"):
            if not segment:
                continue
            node = node.get_child(segment)
            if node is None:
                return None
        return node

    def resolve(self) -> list[str]:
        """Return download URLs for this node.

        - For ``dataset`` nodes: returns ``[self.url]``.
        - For other nodes: collects URLs from all descendant leaves.
        """
        if self.node_type == "dataset" and self.url is not None:
            return [self.url]

        urls: list[str] = []
        for child in self.list_children().values():
            urls.extend(child.resolve())
        return urls

    def tree_summary(self, max_items: int = 20) -> str:
        """Return a compact tree view."""
        lines = [f"{self.name}/  — {self.description}"]
        children = self.list_children()
        items = list(children.values())
        for child in items[:max_items]:
            prefix = "├── " if child != items[-1] else "└── "
            count = ""
            if child.node_type != "dataset" and child.child_count > 0:
                count = f" ({child.child_count})"
            lines.append(f"  {prefix}{child.name}/{count}  — {child.description}")
        if len(items) > max_items:
            lines.append(f"  ... and {len(items) - max_items} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Legacy types (kept for backward compatibility)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DatasetInfo:
    """Describes a dataset within a simulation source (legacy)."""

    path: str
    description: str = ""
    pattern: str | None = None
    chunks: int | None = None

    def expand_urls(self, base_url: str) -> list[str]:
        if self.pattern is not None and self.chunks is not None:
            return [
                f"{base_url}{self.path}{self.pattern.format(chunk=i)}"
                for i in range(self.chunks)
            ]
        return [f"{base_url}{self.path}"]


@dataclass(slots=True)
class SimulationSource:
    """A named source of cosmological simulation data (legacy).

    Prefer :class:`SourceNode` for new code.
    """

    name: str
    description: str
    base_url: str
    auth: object | None = None
    structure: Literal["flat", "mirror", "pattern"] = "mirror"
    datasets: dict[str, DatasetInfo] = field(default_factory=dict)
    group: str = ""

    def resolve(self, dataset_name_or_url: str) -> list[str]:
        if dataset_name_or_url.startswith(("http://", "https://")):
            return [dataset_name_or_url]
        try:
            ds = self.datasets[dataset_name_or_url]
        except KeyError:
            raise KeyError(f"Unknown dataset: {dataset_name_or_url!r}") from None
        return ds.expand_urls(self.base_url)

    def to_node(self) -> SourceNode:
        """Convert this legacy source to a SourceNode tree."""
        children: dict[str, SourceNode] = {}
        for ds_name, ds in self.datasets.items():
            urls = ds.expand_urls(self.base_url)
            child_children: dict[str, SourceNode] = {}
            for i, url in enumerate(urls):
                leaf_name = url.rstrip("/").rsplit("/", 1)[-1] or ds_name
                child_children[leaf_name] = SourceNode(
                    name=leaf_name,
                    path=f"{self.name}/{ds_name}/{leaf_name}",
                    description=f"{ds.description} (file {i+1}/{len(urls)})",
                    node_type="dataset",
                    url=url,
                    auth=self.auth,
                    children={},
                )
            children[ds_name] = SourceNode(
                name=ds_name,
                path=f"{self.name}/{ds_name}",
                description=ds.description,
                node_type="category",
                child_count=len(urls),
                children=child_children,
                auth=self.auth,
            )
        return SourceNode(
            name=self.name,
            path=self.name,
            description=self.description,
            node_type="group",
            child_count=len(self.datasets),
            children=children,
            auth=self.auth,
            base_url=self.base_url,
        )
