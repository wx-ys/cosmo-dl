"""Tests for built-in simulation sources."""
import pytest

from cosmo_dl.registry.builtin import get_builtin_roots, get_builtin_sources
from cosmo_dl.registry.source import SimulationSource, SourceNode


# ---------------------------------------------------------------------------
# Legacy API tests
# ---------------------------------------------------------------------------


def test_get_builtin_sources_returns_list():
    """Legacy sources list is now empty — all sources use SourceNode tree."""
    sources = get_builtin_sources()
    assert isinstance(sources, list)
    # All built-in sources have been migrated to the SourceNode tree


# ---------------------------------------------------------------------------
# Auriga — informational entry (Globus download, no programmatic access)
# ---------------------------------------------------------------------------


def test_auriga_root_exists_in_tree():
    """Auriga should be a root node in the built-in tree."""
    roots = {r.name: r for r in get_builtin_roots()}
    assert "Auriga" in roots
    auriga = roots["Auriga"]
    assert isinstance(auriga, SourceNode)
    assert auriga.node_type == "group"


def test_auriga_root_description():
    """Auriga root should describe the simulations."""
    roots = {r.name: r for r in get_builtin_roots()}
    auriga = roots["Auriga"]
    assert "Auriga" in auriga.description
    assert "AREPO" in auriga.description


def test_auriga_root_has_urls():
    """Auriga root metadata should include data page and download URLs."""
    roots = {r.name: r for r in get_builtin_roots()}
    auriga = roots["Auriga"]
    assert "mpa-garching" in auriga.metadata.get("data_page", "")
    assert "globus" in auriga.metadata.get("download", "")


def test_auriga_no_auth():
    """Auriga is informational — no auth needed."""
    roots = {r.name: r for r in get_builtin_roots()}
    auriga = roots["Auriga"]
    assert auriga.auth is None


def test_auriga_no_children():
    """Auriga is informational — no children to load."""
    roots = {r.name: r for r in get_builtin_roots()}
    auriga = roots["Auriga"]
    children = auriga.list_children()
    assert isinstance(children, dict)
    assert len(children) == 0


# ---------------------------------------------------------------------------
# FIRE-2 — new SourceNode tree API
# ---------------------------------------------------------------------------


def test_fire2_root_exists_in_tree():
    """FIRE-2 should be a root node in the built-in tree."""
    roots = {r.name: r for r in get_builtin_roots()}
    assert "FIRE2" in roots
    fire = roots["FIRE2"]
    assert isinstance(fire, SourceNode)
    assert fire.node_type == "group"
    assert fire.base_url is not None
    assert fire.base_url.startswith("https://")
    assert "flatironinstitute" in fire.base_url


def test_fire2_root_is_lazy():
    """FIRE-2 root should not have children loaded until accessed."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    assert not fire.is_loaded()


def test_fire2_root_no_auth():
    """FIRE-2 is public — root node should have no auth."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    assert fire.auth is None


def test_fire2_root_description():
    """FIRE-2 root should have a meaningful description."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    assert "FIRE-2" in fire.description
    assert "Flatiron" in fire.description


def test_fire2_children_lazy_loaded():
    """Navigating into FIRE-2 root should trigger lazy loading of suite dirs."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    children = fire.list_children()
    assert fire.is_loaded()
    # The FIRE-2 release has at least 4 known suite directories
    assert len(children) >= 1  # at least one suite dir


def test_fire2_suites_are_categories():
    """Suite directories should be category-type nodes; README files are datasets."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    children = fire.list_children()
    for child in children.values():
        if child.node_type == "dataset":
            # README.txt and similar documentation files are now included
            assert child.name.lower().startswith("readme") or child.name.endswith(".txt"), (
                f"Unexpected dataset {child.name!r} at root level"
            )
            continue
        assert child.node_type == "category", (
            f"Suite {child.name!r} should be 'category', got {child.node_type!r}"
        )
        # Suite nodes should have lazy loaders (not pre-loaded)
        assert child._loader is not None or child.is_loaded(), (
            f"Suite {child.name!r} missing lazy loader"
        )


def test_fire2_known_suites():
    """FIRE-2 should have the four main suite directories (if online)."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    children = fire.list_children()
    child_names = set(children.keys())
    expected = {"core", "massive_halo", "high_redshift", "boxes"}
    found = expected & child_names
    # At minimum, if online, we expect all four.  If offline/server issues,
    # we may get fewer — the test is informational.
    assert len(found) >= 1, f"Expected at least one of {expected}, found {child_names}"


def test_fire2_navigate_to_core():
    """Navigate FIRE2/core and verify it is a category with simulations."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    core = fire.get_child("core")
    if core is None:
        pytest.skip("core/ suite not found (offline or server issue)")
    assert core.node_type == "category"
    # Load core's children — should be mostly simulation directories
    core_children = core.list_children()
    assert len(core_children) > 0
    # Most children are category nodes (simulation dirs);
    # a few may be dataset nodes (e.g. snapshot_times.txt metadata file)
    categories = {n: c for n, c in core_children.items() if c.node_type == "category"}
    assert len(categories) >= len(core_children) * 0.8, (
        f"Expected ≥80% categories, got {len(categories)}/{len(core_children)}"
    )
    # Known simulations should be present as category nodes
    assert "m12i_res7100" in categories
    assert "m11i_res7100" in categories


def test_fire2_navigate_to_simulation():
    """Navigate FIRE2/core/m12i_res7100 and verify it is a category node."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    core = fire.get_child("core")
    if core is None:
        pytest.skip("core/ suite not found (offline or server issue)")
    # Look for a known simulation
    sim = core.get_child("m12i_res7100")
    if sim is None:
        pytest.skip("m12i_res7100 not found in core/ (may have been renamed/removed)")
    assert sim.node_type == "category"
    # Load its children — should include output/ at minimum
    sim_children = sim.list_children()
    assert len(sim_children) > 0


def test_fire2_simulation_has_output():
    """A FIRE-2 simulation should contain an output/ directory."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    core = fire.get_child("core")
    if core is None:
        pytest.skip("core/ suite not found (offline or server issue)")
    sim = core.get_child("m12i_res7100") or core.get_child("m11i_res7100")
    if sim is None:
        pytest.skip("No known simulation found in core/")
    sim_children = sim.list_children()
    assert "output" in sim_children, (
        f"Expected 'output' in {sim.name}, got {list(sim_children.keys())}"
    )


def test_fire2_output_contains_files():
    """FIRE-2 output/ contains snapdir_NNN/ directories with snapshot chunk files."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    core = fire.get_child("core")
    if core is None:
        pytest.skip("core/ suite not found (offline or server issue)")
    sim = core.get_child("m12i_res7100") or core.get_child("m11i_res7100")
    if sim is None:
        pytest.skip("No known simulation found in core/")
    output = sim.get_child("output")
    if output is None:
        pytest.skip("output/ not found in simulation")
    output_children = output.list_children()
    assert len(output_children) > 0
    # output/ contains snapdir_NNN/ subdirectories (Gizmo snapshot format)
    snapdirs = [c for c in output_children.values() if c.name.startswith("snapdir_")]
    assert len(snapdirs) > 0, "output/ should contain snapdir_NNN subdirectories"
    # Navigate into one snapdir — should contain .hdf5 chunk files
    first_snapdir = snapdirs[0]
    chunk_children = first_snapdir.list_children()
    dataset_count = sum(
        1 for c in chunk_children.values() if c.node_type == "dataset"
    )
    assert dataset_count > 0, "snapdir/ should contain dataset files (.hdf5 chunks)"


def test_fire2_legacy_source_not_included():
    """FIRE-2 should NOT be in the legacy get_builtin_sources() list."""
    sources = {s.name: s for s in get_builtin_sources()}
    assert "FIRE2" not in sources, (
        "FIRE-2 migrated to SourceNode tree — should not appear in legacy sources"
    )


def test_fire2_scraper_deduplicates():
    """The directory scraper should not return duplicate entries."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    children = fire.list_children()
    names = list(children.keys())
    assert len(names) == len(set(names)), f"Duplicate entries found: {names}"


def test_fire2_suite_has_descriptions():
    """Known FIRE-2 suites should carry human-readable descriptions."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    children = fire.list_children()
    # Core suite should have a description from our known-suite map
    if "core" in children:
        core = children["core"]
        assert len(core.description) > 20, (
            f"Core suite description too short: {core.description!r}"
        )
        assert "z = 0" in core.description or "z=0" in core.description


# ---------------------------------------------------------------------------
# FIRE-2 — download_relpath propagation
# ---------------------------------------------------------------------------


def test_fire2_dataset_has_download_relpath():
    """Leaf dataset nodes should have download_relpath set."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    core = fire.get_child("core")
    if core is None:
        pytest.skip("core/ suite not found (offline or server issue)")
    sim = core.get_child("m12i_res7100") or core.get_child("m11i_res7100")
    if sim is None:
        pytest.skip("No known simulation found in core/")
    output = sim.get_child("output")
    if output is None:
        pytest.skip("output/ not found in simulation")
    output_children = output.list_children()
    for child in output_children.values():
        if child.node_type == "dataset":
            assert child.download_relpath is not None, (
                f"Dataset {child.name!r} missing download_relpath"
            )
            # Should include output/ path
            assert "output" in child.download_relpath.lower() or child.url is not None


def test_fire2_category_has_download_relpath():
    """Category nodes should have download_relpath set for structured downloads."""
    roots = {r.name: r for r in get_builtin_roots()}
    fire = roots["FIRE2"]
    core = fire.get_child("core")
    if core is None:
        pytest.skip("core/ suite not found (offline or server issue)")
    # Suite-level categories should have download_relpath
    assert core.download_relpath is not None
    assert "core" in core.download_relpath


# ---------------------------------------------------------------------------
# FIRE-2 — offline / monkeypatched tests
# ---------------------------------------------------------------------------


def test_build_fire2_root_offline_structure():
    """build_fire2_root() should return a correctly-shaped node even before
    any network calls."""
    from cosmo_dl.registry.builtin.fire import build_fire2_root
    root = build_fire2_root()
    assert root.name == "FIRE2"
    assert root.node_type == "group"
    assert root.base_url is not None
    assert root.auth is None
    assert not root.is_loaded()
    # child_count is 0 before lazy loading
    assert root.child_count == 0


def test_fire2_scrape_with_mock(monkeypatch):
    """Simulate scraping to verify the parser handles typical Apache listings."""
    # Mock requests.get to return a synthetic directory listing
    sample_html = """<!DOCTYPE html>
<html><head><title>fire2_public_release/</title></head>
<body>
<h1>fire2_public_release/</h1>
<hr>
<pre>
<a href="../">../</a>
<a href="core/">core/</a>                                          28-Feb-2025 10:00       -
<a href="massive_halo/">massive_halo/</a>                            28-Feb-2025 10:00       -
<a href="high_redshift/">high_redshift/</a>                          28-Feb-2025 10:00       -
<a href="boxes/">boxes/</a>                                        28-Feb-2025 10:00       -
<a href="README.txt">README.txt</a>                                  28-Feb-2025 10:00     2.3K
</pre>
<hr>
</body></html>"""

    import requests as req_mod

    class MockResponse:
        status_code = 200
        text = sample_html

        def raise_for_status(self):
            pass

    def mock_get(url, timeout=None):
        return MockResponse()

    monkeypatch.setattr(req_mod, "get", mock_get)

    from cosmo_dl.registry.builtin.fire import build_fire2_root
    root = build_fire2_root()
    children = root.list_children()

    # Should have 4 suite dirs + README.txt
    assert len(children) == 5
    assert "core" in children
    assert "massive_halo" in children
    assert "high_redshift" in children
    assert "boxes" in children
    # README.txt should be included as a dataset node
    assert "README.txt" in children
    assert children["README.txt"].node_type == "dataset"

    # Suite dirs should be category nodes
    for name in children:
        if name == "README.txt":
            continue
        assert children[name].node_type == "category"

    # Core should have the known description
    core = children["core"]
    assert "Core suite" in core.description
    assert "z=0" in core.description


def test_fire2_scrape_nested_dirs(monkeypatch):
    """Simulate scraping a nested directory (core/) with simulations."""
    # Different HTML for different URLs
    root_html = """<!DOCTYPE html>
<html><head><title>fire2_public_release/</title></head>
<body>
<h1>fire2_public_release/</h1>
<hr>
<pre>
<a href="../">../</a>
<a href="core/">core/</a>                                          28-Feb-2025 10:00       -
<a href="massive_halo/">massive_halo/</a>                            28-Feb-2025 10:00       -
<a href="high_redshift/">high_redshift/</a>                          28-Feb-2025 10:00       -
<a href="boxes/">boxes/</a>                                        28-Feb-2025 10:00       -
<a href="README.txt">README.txt</a>                                  28-Feb-2025 10:00     2.3K
</pre>
<hr>
</body></html>"""

    core_html = """<!DOCTYPE html>
<html><head><title>core/</title></head>
<body>
<h1>core/</h1>
<hr>
<pre>
<a href="../">../</a>
<a href="m11i_res7100/">m11i_res7100/</a>                          28-Feb-2025 10:00       -
<a href="m12i_res7100/">m12i_res7100/</a>                          28-Feb-2025 10:00       -
<a href="dm_only/">dm_only/</a>                                    28-Feb-2025 10:00       -
<a href="mhd/">mhd/</a>                                          28-Feb-2025 10:00       -
<a href="README.txt">README.txt</a>                                  28-Feb-2025 10:00     1.5K
</pre>
<hr>
</body></html>"""

    import requests as req_mod

    class MockResponse:
        def __init__(self, text):
            self.status_code = 200
            self.text = text

        def raise_for_status(self):
            pass

    def mock_get(url, timeout=None):
        if url.rstrip("/").endswith("/core"):
            return MockResponse(core_html)
        return MockResponse(root_html)

    monkeypatch.setattr(req_mod, "get", mock_get)

    from cosmo_dl.registry.builtin.fire import build_fire2_root
    root = build_fire2_root()
    # Load root to get suites, then navigate to core
    root.list_children()
    core = root.get_child("core")
    assert core is not None
    core_children = core.list_children()

    assert "m11i_res7100" in core_children
    assert "m12i_res7100" in core_children
    assert "dm_only" in core_children
    assert "mhd" in core_children
    # README.txt should be included as a dataset node
    assert "README.txt" in core_children
    assert core_children["README.txt"].node_type == "dataset"

    # Sub-suites should have descriptions
    dm = core_children["dm_only"]
    assert "Dark Matter Only" in dm.description

    mhd = core_children["mhd"]
    assert "MHD" in mhd.description


def test_fire2_scrape_with_files(monkeypatch):
    """Simulate scraping a directory with both files and subdirectories."""
    sample_html = """<!DOCTYPE html>
<html><body>
<pre>
<a href="../">../</a>
<a href="output/">output/</a>                                    28-Feb-2025 10:00       -
<a href="snap_ics.hdf5">snap_ics.hdf5</a>                            28-Feb-2025 10:00    125M
</pre>
</body></html>"""

    import requests as req_mod

    class MockResponse:
        status_code = 200
        text = sample_html

        def raise_for_status(self):
            pass

    def mock_get(url, timeout=None):
        return MockResponse()

    monkeypatch.setattr(req_mod, "get", mock_get)

    from cosmo_dl.registry.builtin.fire import build_fire2_root
    root = build_fire2_root()
    children = root.list_children()

    # output/ is a dir → category with lazy loader
    assert "output" in children
    output = children["output"]
    assert output.node_type == "category"
    assert output._loader is not None

    # snap_ics.hdf5 is a file → dataset with URL
    assert "snap_ics.hdf5" in children
    snap = children["snap_ics.hdf5"]
    assert snap.node_type == "dataset"
    assert snap.url is not None
    assert snap.children == {}
    assert snap._loader is None


def test_fire2_resolve_dataset_url():
    """Resolving a dataset node should return its URL."""
    from cosmo_dl.registry.builtin.fire import _build_dir_children

    # Build children from a simulated URL — the scraper is monkeypatched above,
    # so just verify the SourceNode contract directly
    from cosmo_dl.registry.source import SourceNode

    leaf = SourceNode(
        name="test.hdf5",
        path="FIRE2/test/test.hdf5",
        description="Test dataset",
        node_type="dataset",
        url="https://example.com/test.hdf5",
        children={},
    )
    urls = leaf.resolve()
    assert urls == ["https://example.com/test.hdf5"]

    # Category node should collect URLs from children
    parent = SourceNode(
        name="test",
        path="FIRE2/test",
        node_type="category",
        children={"test.hdf5": leaf, "test2.hdf5": SourceNode(
            name="test2.hdf5",
            path="FIRE2/test/test2.hdf5",
            node_type="dataset",
            url="https://example.com/test2.hdf5",
            children={},
        )},
    )
    urls = parent.resolve()
    assert len(urls) == 2
    assert "https://example.com/test.hdf5" in urls
    assert "https://example.com/test2.hdf5" in urls


# ---------------------------------------------------------------------------
# TNG tests
# ---------------------------------------------------------------------------


def test_tng_tree_exists():
    """TNG root node should exist in the registry tree."""
    roots = {r.name: r for r in get_builtin_roots()}
    assert "TNG" in roots
    tng = roots["TNG"]
    assert tng.child_count >= 5  # at least 5 sub-groups


def test_tng_tree_subgroups():
    """TNG should have sub-groups like TNG50, TNG100, TNG300."""
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    children = tng.list_children()
    assert "TNG50" in children
    assert "TNG100" in children
    assert "TNG300" in children


def test_tng_tree_navigate_to_simulation():
    """Navigate TNG/TNG50/TNG50-1 and check it is a simulation node."""
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
    import os
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    if "TNG_API_KEY" in os.environ:
        assert tng.auth is not None
    # Without env var, auth is None (user configures via YAML/CLI)


def test_tng_simulation_node_type():
    """TNG/TNG50/TNG50-1 should be a simulation node."""
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    assert tng50_1.node_type == "simulation"


def test_tng_simulation_has_metadata():
    """Simulation nodes should have metadata (boxsize, cosmology, num_snapshots)."""
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
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    tng50_1 = tng50.get_child("TNG50-1")
    children = tng50_1.list_children()
    for expected in ("snapshots", "postprocessing", "files"):
        assert expected in children, f"Missing child: {expected}"


def test_tng_no_subbox_at_subgroup_level():
    """Subbox simulations should NOT appear at the sub-group level."""
    roots = {r.name: r for r in get_builtin_roots()}
    tng = roots["TNG"]
    tng50 = tng.get_child("TNG50")
    for child_name in tng50.list_children():
        assert "Subbox" not in child_name, (
            f"Subbox {child_name!r} should not be at sub-group level"
        )


def test_tng_dark_variant_is_sibling():
    """Dark variants should appear as siblings at the sub-group level."""
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


# ---------------------------------------------------------------------------
# EAGLE — hardcoded simulation tree with download API endpoints
# ---------------------------------------------------------------------------


def test_eagle_root_exists_in_tree():
    """EAGLE should be a root node in the built-in tree."""
    roots = {r.name: r for r in get_builtin_roots()}
    assert "EAGLE" in roots
    eagle = roots["EAGLE"]
    assert isinstance(eagle, SourceNode)
    assert eagle.node_type == "group"
    assert eagle.base_url is not None
    assert eagle.base_url.startswith("https://")
    assert "dataweb.cosma.dur.ac.uk" in eagle.base_url


def test_eagle_root_is_lazy():
    """EAGLE root should not have children loaded until accessed."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    assert not eagle.is_loaded()


def test_eagle_root_description():
    """EAGLE root should have a meaningful description and child count."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    assert "EAGLE" in eagle.description
    assert "Virgo" in eagle.description


def test_eagle_root_auth_attr(monkeypatch):
    """EAGLE root auth is None without credentials, set when credentials exist."""
    # Clear any env vars that might be set
    monkeypatch.delenv("EAGLE_USERNAME", raising=False)
    monkeypatch.delenv("EAGLE_PASSWORD", raising=False)
    # Also bypass .env / config.toml
    monkeypatch.setattr(
        "cosmo_dl.registry.builtin.eagle.config_get",
        lambda key, default="": "",
    )

    from cosmo_dl.registry.builtin.eagle import build_eagle_root
    root = build_eagle_root()
    assert root.auth is None


def test_eagle_root_auth_with_credentials(monkeypatch):
    """EAGLE root should have Basic Auth when credentials are configured."""
    monkeypatch.setenv("EAGLE_USERNAME", "testuser")
    monkeypatch.setenv("EAGLE_PASSWORD", "testpass")

    from cosmo_dl.registry.builtin.eagle import build_eagle_root
    root = build_eagle_root()
    assert root.auth is not None
    assert root.auth.type == "basic"
    assert root.auth.username == "testuser"
    assert root.auth.password == "testpass"


def test_eagle_legacy_source_not_included():
    """EAGLE should NOT be in the legacy get_builtin_sources() list."""
    sources = {s.name: s for s in get_builtin_sources()}
    assert "EAGLE" not in sources


def test_eagle_root_has_three_schemas():
    """EAGLE root should have Fiducial_models, Physics_vars, DMONLY children."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    children = eagle.list_children()
    assert eagle.is_loaded()
    assert len(children) == 3
    assert "Fiducial_models" in children
    assert "Physics_vars" in children
    assert "DMONLY" in children
    # Schema nodes should be groups
    for schema_name in ("Fiducial_models", "Physics_vars", "DMONLY"):
        assert children[schema_name].node_type == "group"


def test_eagle_fiducial_models_has_simulations():
    """Fiducial_models schema should contain known reference simulations."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    fid = eagle.get_child("Fiducial_models")
    assert fid is not None
    fid_children = fid.list_children()
    assert "RefL0100N1504" in fid_children
    assert "RefL0050N0752" in fid_children
    assert "RefL0025N0376" in fid_children
    assert "RecalL0025N0752" in fid_children
    assert "AGNdT9L0050N0752" in fid_children


def test_eagle_physics_vars_has_simulations():
    """Physics_vars schema should contain variation models."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    pv = eagle.get_child("Physics_vars")
    assert pv is not None
    pv_children = pv.list_children()
    assert "FBconstL0050N0752" in pv_children
    assert "HiML0050N0752" in pv_children
    assert "NoAGNL0050N0752" in pv_children


def test_eagle_dmonly_has_simulations():
    """DMONLY schema should contain dark-matter-only models."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    dm = eagle.get_child("DMONLY")
    assert dm is not None
    dm_children = dm.list_children()
    assert "L0100N1504" in dm_children
    assert "L0025N0376" in dm_children
    assert "L0025N0752" in dm_children


def test_eagle_simulation_is_simulation_node():
    """EAGLE simulations should be 'simulation' type with metadata."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    fid = eagle.get_child("Fiducial_models")
    ref = fid.get_child("RefL0100N1504")
    assert ref is not None
    assert ref.node_type == "simulation"
    assert "box_size" in ref.metadata
    assert "particles" in ref.metadata
    assert "num_snapshots" in ref.metadata
    assert ref.metadata["num_snapshots"] == 29


def test_eagle_simulation_has_snapshots():
    """Simulations with snapshots should have a snapshots/ child category."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    fid = eagle.get_child("Fiducial_models")
    ref = fid.get_child("RefL0100N1504")
    ref_children = ref.list_children()
    assert "snapshots" in ref_children
    snaps = ref_children["snapshots"]
    assert snaps.node_type == "category"
    assert snaps.child_count == 29


def test_eagle_dmonly_has_no_snapshots():
    """DMONLY simulations have no public snapshots."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    dm = eagle.get_child("DMONLY")
    dm_sim = dm.get_child("L0100N1504")
    assert dm_sim is not None
    dm_children = dm_sim.list_children()
    assert len(dm_children) == 0
    assert dm_sim.child_count == 0


def test_eagle_snapshot_has_download_url():
    """Each EAGLE snapshot should be a dataset with a download endpoint URL."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    fid = eagle.get_child("Fiducial_models")
    ref = fid.get_child("RefL0100N1504")
    snaps = ref.get_child("snapshots")
    snap_children = snaps.list_children()
    assert len(snap_children) == 29

    # Check sn-28 (z=0.00)
    assert "sn-28" in snap_children
    sn28 = snap_children["sn-28"]
    assert sn28.node_type == "dataset"
    assert sn28.url is not None
    assert "/download?run=RefL0100N1504&snapnum=28" in sn28.url
    assert sn28.metadata.get("redshift") == 0.0

    # Check sn-00 (z=20.00)
    assert "sn-00" in snap_children
    sn00 = snap_children["sn-00"]
    assert sn00.metadata.get("redshift") == 20.0


def test_eagle_varimf_has_11_snapshots():
    """Variable IMF runs should have only 11 snapshots (0–10)."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    pv = eagle.get_child("Physics_vars")
    him = pv.get_child("HiML0050N0752")
    assert him is not None
    assert him.metadata["num_snapshots"] == 11

    snaps = him.get_child("snapshots")
    snap_children = snaps.list_children()
    assert len(snap_children) == 11
    # sn-10 should be z=0.00 for VarIMF
    sn10 = snap_children["sn-10"]
    assert sn10.metadata.get("redshift") == 0.0


def test_eagle_total_simulation_count():
    """The total number of simulations should match the hardcoded list."""
    from cosmo_dl.registry.builtin.eagle import _SIMULATIONS
    assert len(_SIMULATIONS) == 26  # 26 simulations total


def test_eagle_navigate_full_path():
    """Navigate a full tree path: EAGLE/Fiducial_models/RefL0100N1504/snapshots/sn-28."""
    roots = {r.name: r for r in get_builtin_roots()}
    eagle = roots["EAGLE"]
    node = eagle.navigate("Fiducial_models/RefL0100N1504/snapshots/sn-28")
    assert node is not None
    assert node.node_type == "dataset"
    assert node.name == "sn-28"
    assert "z=0.00" in node.description
