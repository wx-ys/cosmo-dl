"""Registry source types — SimulationSource and DatasetInfo."""
from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class DatasetInfo:
    """Describes a dataset within a simulation source."""

    path: str
    description: str = ""
    pattern: str | None = None
    chunks: int | None = None

    def expand_urls(self, base_url: str) -> list[str]:
        """Expand this dataset into a list of concrete URLs.

        If *pattern* and *chunks* are set, format the pattern with
        ``{chunk}`` substituted for each integer in ``range(chunks)``.
        Otherwise return a single URL joining *base_url* and *path*.
        """
        if self.pattern is not None and self.chunks is not None:
            return [
                f"{base_url}{self.path}{self.pattern.format(chunk=i)}"
                for i in range(self.chunks)
            ]
        return [f"{base_url}{self.path}"]


@dataclass(slots=True)
class SimulationSource:
    """A named source of cosmological simulation data."""

    name: str
    description: str
    base_url: str
    auth: object | None = None  # AuthConfig from cosmo_dl.engine.types
    structure: Literal["flat", "mirror", "pattern"] = "mirror"
    datasets: dict[str, DatasetInfo] = field(default_factory=dict)

    def resolve(self, dataset_name_or_url: str) -> list[str]:
        """Resolve a dataset name or raw URL into a list of concrete URLs.

        If *dataset_name_or_url* starts with ``http://`` or ``https://`` it
        is returned as-is (wrapped in a single-element list).  Otherwise it
        is looked up in :attr:`datasets` and expanded via
        :meth:`DatasetInfo.expand_urls`.  A :class:`KeyError` is raised for
        unknown dataset names.
        """
        if dataset_name_or_url.startswith(("http://", "https://")):
            return [dataset_name_or_url]

        try:
            ds = self.datasets[dataset_name_or_url]
        except KeyError:
            raise KeyError(f"Unknown dataset: {dataset_name_or_url!r}") from None

        return ds.expand_urls(self.base_url)
