"""Tests for the Registry class."""
import tempfile
import pytest
from cosmo_dl.registry.registry import Registry
from cosmo_dl.registry.source import SimulationSource, DatasetInfo


class TestRegistry:
    def test_registry_loads_builtin_sources(self):
        reg = Registry()
        names = reg.list()
        assert "FIRE2" in names
        assert "Auriga" in names

    def test_get_known_source(self):
        reg = Registry()
        fire2 = reg.get("FIRE2")
        assert fire2 is not None
        assert fire2.name == "FIRE2"

    def test_get_unknown_source_returns_none(self):
        reg = Registry()
        assert reg.get("nonexistent") is None

    def test_resolve_source_dataset(self):
        reg = Registry()
        # Resolve a specific snapdir for predictable scope
        urls = reg.resolve("FIRE2/core/m12i_res7100/output/snapdir_000")
        assert len(urls) > 0
        for url in urls:
            assert url.startswith("https://")

    def test_resolve_unknown_source_raises(self):
        reg = Registry()
        with pytest.raises(ValueError, match="Unknown source"):
            reg.resolve("NoSuchSource/dataset")

    def test_resolve_raw_url_passthrough(self):
        reg = Registry()
        urls = reg.resolve("https://example.com/file.hdf5")
        assert urls == ["https://example.com/file.hdf5"]

    def test_resolve_missing_dataset_raises(self):
        reg = Registry()
        with pytest.raises(KeyError, match="Unknown dataset"):
            reg.resolve("FIRE2/nonexistent")

    def test_register_custom_source(self):
        """Custom sources are added as root nodes via .to_node()."""
        reg = Registry()
        custom = SimulationSource(
            name="Custom", description="C", base_url="https://x.com/"
        )
        node = custom.to_node()
        reg._roots[node.name] = node
        assert "Custom" in reg.list()
        assert reg.get_node("Custom") is node

    def test_user_config_loaded(self):
        yaml_content = """
sources:
  user-sim:
    description: From YAML
    base_url: https://user-sim.edu/
    datasets:
      data:
        path: files/
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            reg = Registry(user_config_path=f.name)
        assert "user-sim" in reg.list()
        src = reg.get("user-sim")
        assert src.base_url == "https://user-sim.edu/"
