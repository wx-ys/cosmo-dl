"""Tests for YAML source loader."""

import os
import tempfile

from cosmo_dl.registry.loader import load_sources_from_yaml

SAMPLE_YAML = """
sources:
  my-sim:
    description: My custom simulation
    base_url: https://myserver.edu/data/
    auth:
      type: basic
      username: user
      password: pass
    datasets:
      snap-100:
        path: snapdir_100/
        pattern: "snapshot_100.{chunk}.hdf5"
        chunks: 4
        description: Snapshot 100
"""


class TestLoadSourcesFromYaml:
    def test_load_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(SAMPLE_YAML)
            f.flush()
            sources = load_sources_from_yaml(f.name)

        assert len(sources) == 1
        src = sources[0]
        assert src.name == "my-sim"
        assert src.base_url == "https://myserver.edu/data/"
        assert src.auth is not None
        assert src.auth.type == "basic"
        assert "snap-100" in src.datasets

    def test_load_expands_urls(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(SAMPLE_YAML)
            f.flush()
            sources = load_sources_from_yaml(f.name)

        src = sources[0]
        urls = src.resolve("snap-100")
        assert len(urls) == 4
        assert "snapshot_100.0.hdf5" in urls[0]
        assert "snapshot_100.3.hdf5" in urls[3]

    def test_load_env_var_substitution(self):
        os.environ["TEST_USER"] = "envuser"
        os.environ["TEST_PASS"] = "envpass"
        yaml_content = """
sources:
  env-sim:
    description: Test env vars
    base_url: https://example.com/
    auth:
      type: basic
      username: ${TEST_USER}
      password: ${TEST_PASS}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            sources = load_sources_from_yaml(f.name)

        assert sources[0].auth.username == "envuser"
        assert sources[0].auth.password == "envpass"

    def test_load_empty_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("sources: {}\n")
            f.flush()
            sources = load_sources_from_yaml(f.name)
        assert sources == []

    def test_load_missing_file_returns_empty(self):
        sources = load_sources_from_yaml("/nonexistent/path.yaml")
        assert sources == []
