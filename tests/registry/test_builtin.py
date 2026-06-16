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


def test_tng_tree_exists():
    """TNG root node should exist in the registry tree."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    assert "TNG" in roots
    tng = roots["TNG"]
    assert tng.child_count >= 5  # at least 5 sub-groups


def test_tng_tree_subgroups():
    """TNG should have sub-groups like TNG50, TNG100, TNG300."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    children = tng.list_children()
    assert "TNG50" in children
    assert "TNG100" in children
    assert "TNG300" in children


def test_tng_tree_navigate_to_simulation():
    """Navigate TNG/TNG50/TNG50-1 and check it has categories."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    assert tng50 is not None
    tng50_1 = tng50.get_child("TNG50-1")
    assert tng50_1 is not None
    # Load the simulation's categories (lazy)
    cats = tng50_1.list_children()
    assert tng50_1.is_loaded()
    assert len(cats) >= 1  # at least one file category (groupcat, snapshots, etc.)
    # Each category should have children (indices)
    first_cat = list(cats.values())[0]
    assert first_cat.child_count > 0


def test_tng_tree_has_auth():
    """TNG root should have auth if TNG_API_KEY is set."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    import os
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    if "TNG_API_KEY" in os.environ:
        assert tng.auth is not None
    # Without env var, auth is None (user configures via YAML/CLI)
