"""Test top-level package imports."""


def test_top_level_imports():
    import cosmo_dl

    assert cosmo_dl.download is not None
    assert cosmo_dl.explore is not None
    assert cosmo_dl.list_sources is not None
    assert cosmo_dl.DownloadResult is not None
    assert cosmo_dl.FileEntry is not None
    assert cosmo_dl.SimulationSource is not None
