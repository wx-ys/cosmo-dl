"""Tests for built-in simulation sources."""
from cosmo_dl.registry.builtin import get_builtin_sources
from cosmo_dl.registry.source import SimulationSource


def test_get_builtin_sources_returns_list():
    sources = get_builtin_sources()
    assert len(sources) >= 2
    assert all(isinstance(s, SimulationSource) for s in sources)


def test_fire_source_exists():
    sources = {s.name: s for s in get_builtin_sources()}
    assert "FIRE" in sources
    fire = sources["FIRE"]
    assert fire.base_url.startswith("https://")
    assert "m11i_res7100" in fire.datasets


def test_auriga_source_exists():
    sources = {s.name: s for s in get_builtin_sources()}
    assert "Auriga" in sources
    auriga = sources["Auriga"]
    assert "halo-1" in auriga.datasets or any(
        d.startswith("halo") for d in auriga.datasets
    )


def test_fire_resolve_generates_urls():
    sources = {s.name: s for s in get_builtin_sources()}
    fire = sources["FIRE"]
    urls = fire.resolve("m11i_res7100")
    assert len(urls) > 0
    for url in urls:
        assert url.startswith("https://")


def test_auriga_resolve_generates_urls():
    sources = {s.name: s for s in get_builtin_sources()}
    auriga = sources["Auriga"]
    halo_dataset = next(
        (k for k in auriga.datasets if k.startswith("halo-")), None
    )
    if halo_dataset:
        urls = auriga.resolve(halo_dataset)
        assert len(urls) > 0
        for url in urls:
            assert url.startswith("https://")
