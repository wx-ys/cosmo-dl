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


def test_tng_sources_exist():
    sources = {s.name: s for s in get_builtin_sources()}
    assert "TNG50-1" in sources
    assert "TNG100-1" in sources
    assert "TNG300-1" in sources


def test_tng_source_has_groupcat_datasets():
    sources = {s.name: s for s in get_builtin_sources()}
    tng50 = sources["TNG50-1"]
    assert "groupcat-0" in tng50.datasets
    assert "groupcat-99" in tng50.datasets
    assert len(tng50.datasets) == 200  # 100 groupcat + 100 snapshot


def test_tng_source_resolve_groupcat():
    sources = {s.name: s for s in get_builtin_sources()}
    tng50 = sources["TNG50-1"]
    urls = tng50.resolve("groupcat-99")
    assert len(urls) == 1
    assert "files/groupcat-99/" in urls[0]
    assert urls[0].startswith("http://www.tng-project.org/api/TNG50-1/")


def test_tng_source_has_api_auth():
    """TNG source should have api-key auth when TNG_API_KEY is set, or None otherwise."""
    import os
    sources = {s.name: s for s in get_builtin_sources()}
    tng50 = sources["TNG50-1"]
    if "TNG_API_KEY" in os.environ:
        assert tng50.auth is not None
        assert tng50.auth.type == "api-key"  # type: ignore[union-attr]
    else:
        # Without env var, auth is None (user must configure via YAML)
        pass
