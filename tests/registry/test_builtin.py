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
    """Navigate TNG/TNG50/TNG50-1 and check it is a simulation node."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    assert tng50 is not None
    tng50_1 = tng50.get_child("TNG50-1")
    assert tng50_1 is not None
    assert tng50_1.node_type == "simulation"
    # Load the simulation's children (lazy)
    children = tng50_1.list_children()
    assert tng50_1.is_loaded()
    # Should have snapshots, postprocessing, files at minimum
    assert "snapshots" in children
    assert "postprocessing" in children
    assert "files" in children
    # Snapshots should have the expected count
    assert children["snapshots"].child_count > 0


def test_tng_tree_has_auth():
    """TNG root should have auth if TNG_API_KEY is set."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    import os
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    if "TNG_API_KEY" in os.environ:
        assert tng.auth is not None
    # Without env var, auth is None (user configures via YAML/CLI)


def test_tng_simulation_node_type():
    """TNG/TNG50/TNG50-1 should be a simulation node."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    assert tng50_1.node_type == "simulation"


def test_tng_simulation_has_metadata():
    """Simulation nodes should have metadata (boxsize, cosmology, num_snapshots)."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    assert "num_snapshots" in tng50_1.metadata
    assert "cosmology" in tng50_1.metadata
    assert "boxsize" in tng50_1.metadata
    assert isinstance(tng50_1.metadata["num_snapshots"], int)


def test_tng_simulation_has_expected_children():
    """Simulation detail should have snapshots, postprocessing, files sections."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    children = tng50_1.list_children()
    for expected in ("snapshots", "postprocessing", "files"):
        assert expected in children, f"Missing child: {expected}"


def test_tng_no_subbox_at_subgroup_level():
    """Subbox simulations should NOT appear at the sub-group level."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    for child_name in tng50.list_children():
        assert "Subbox" not in child_name, (
            f"Subbox {child_name!r} should not be at sub-group level"
        )


def test_tng_dark_variant_is_sibling():
    """Dark variants should appear as siblings at the sub-group level."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    siblings = tng50.list_children()
    # Dark variant is a sibling, not a child of the main simulation
    assert "TNG50-1-Dark" in siblings
    assert "TNG50-1" in siblings
    dark = siblings["TNG50-1-Dark"]
    assert dark.node_type == "simulation"


def test_tng_dark_variant_has_own_data():
    """Dark variant simulations should have their own data sections."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    dark = tng50.get_child("TNG50-1-Dark")
    assert dark is not None
    dark_children = dark.list_children()
    assert "snapshots" in dark_children
    assert dark.metadata.get("num_snapshots", 0) > 0


def test_tng_snapshot_children():
    """Snapshot nodes should have snapshot/ and groupcat/ children."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    snaps = tng50_1.get_child("snapshots")
    assert snaps is not None
    snap_children = snaps.list_children()
    # Should have at least some snapshot nodes
    assert len(snap_children) > 0
    first_snap = list(snap_children.values())[0]
    assert first_snap.child_count == 2  # snapshot + groupcat


def test_tng_snapshot_file_download_relpath():
    """Snapshot file children should have download_relpath set."""
    from cosmo_dl.registry.builtin import get_builtin_roots
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    snaps = tng50_1.get_child("snapshots")
    # Load snapshot file children (this will be empty in offline mode)
    first_snap = list(snaps.list_children().values())[0]
    file_children = first_snap.list_children()
    # snapshot/ and groupcat/ should have download_relpath
    if "snapshot" in file_children:
        snap_node = file_children["snapshot"]
        assert snap_node.download_relpath is not None
        assert "snapdir" in snap_node.download_relpath or "output" in snap_node.download_relpath
    if "groupcat" in file_children:
        gc_node = file_children["groupcat"]
        assert gc_node.download_relpath is not None
        assert "groups" in gc_node.download_relpath or "output" in gc_node.download_relpath


def test_tng_fallback_offline(monkeypatch):
    """In offline mode, fallback data produces a usable tree."""
    monkeypatch.setenv("COSMO_DL_OFFLINE", "true")
    from cosmo_dl.registry.builtin.tng import build_tng_root
    root = build_tng_root()
    assert root.name == "TNG"
    children = root.list_children()
    assert len(children) >= 4  # TNG50, TNG100, TNG300, TNG-Cluster/Illustris
    # Navigate one level
    tng50 = children.get("TNG50")
    assert tng50 is not None
    tng50_children = tng50.list_children()
    assert "TNG50-1" in tng50_children


def test_tng_source_info_command():
    """source info should work on simulation nodes."""
    import os
    os.environ["COSMO_DL_OFFLINE"] = "true"
    from click.testing import CliRunner
    from cosmo_dl.cli.main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["source", "info", "TNG/TNG50/TNG50-1"])
    assert result.exit_code == 0
    assert "simulation" in result.output.lower()
    assert "TNG50-1" in result.output
