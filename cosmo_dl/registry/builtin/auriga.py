"""Auriga simulation data source — informational entry.

The Auriga data is hosted on Globus and requires browser-based login.
cosmo-dl does not currently support automated Globus authentication.
Use the links below to browse and download data manually.
"""

from __future__ import annotations

from cosmo_dl.registry.source import SourceNode

_AURIGA_DESCRIPTION = (
    "The Auriga simulations are a set of cosmological zoom simulations "
    "performed with the magneto-hydrodynamics code AREPO."
)

_AURIGA_DATA_PAGE = "https://wwwmpa.mpa-garching.mpg.de/auriga/data.html"
_AURIGA_DOWNLOAD = (
    "https://app.globus.org/file-manager?origin_id=02a2dbb8-f64d-4440-bafe-44b60b964501"
)


def build_auriga_root() -> SourceNode:
    """Return the Auriga root ``SourceNode`` (informational only).

    Auriga data requires Globus browser-based login.  Visit the data
    page for documentation and the Globus file manager to download.

    Returns
    -------
    SourceNode
        Informational root node.  ``node_type`` is ``"group"``,
        ``name`` is ``"Auriga"``.
    """
    return SourceNode(
        name="Auriga",
        path="Auriga",
        description=_AURIGA_DESCRIPTION,
        node_type="group",
        metadata={
            "data_page": _AURIGA_DATA_PAGE,
            "download": _AURIGA_DOWNLOAD,
        },
    )
