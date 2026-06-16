"""Tests for registry source types."""
import pytest
from cosmo_dl.registry.source import SimulationSource, DatasetInfo


class TestDatasetInfo:
    def test_simple_dataset(self):
        ds = DatasetInfo(
            path="snapdir_127/",
            description="Snapshot 127",
        )
        assert ds.path == "snapdir_127/"
        assert ds.pattern is None
        assert ds.chunks is None

    def test_pattern_dataset(self):
        ds = DatasetInfo(
            path="snapdir_127/",
            pattern="snapshot_127.{chunk}.hdf5",
            chunks=8,
            description="Snapshot 127 chunks",
        )
        assert ds.pattern == "snapshot_127.{chunk}.hdf5"
        assert ds.chunks == 8

    def test_expand_urls(self):
        ds = DatasetInfo(
            path="snapdir_127/",
            pattern="snapshot_127.{chunk}.hdf5",
            chunks=4,
        )
        urls = ds.expand_urls("https://host/data/")
        assert len(urls) == 4
        assert urls[0] == "https://host/data/snapdir_127/snapshot_127.0.hdf5"
        assert urls[3] == "https://host/data/snapdir_127/snapshot_127.3.hdf5"

    def test_expand_urls_no_pattern(self):
        ds = DatasetInfo(path="README.txt")
        urls = ds.expand_urls("https://host/data/")
        assert len(urls) == 1
        assert urls[0] == "https://host/data/README.txt"


class TestSimulationSource:
    def test_basic_source(self):
        source = SimulationSource(
            name="TestSim",
            description="A test simulation",
            base_url="https://example.com/data/",
        )
        assert source.name == "TestSim"
        assert source.auth is None
        assert source.datasets == {}

    def test_source_with_datasets(self):
        source = SimulationSource(
            name="TestSim",
            description="Test",
            base_url="https://example.com/data/",
            datasets={
                "snap-99": DatasetInfo(
                    path="snapdir_099/",
                    pattern="snap_099.{chunk}.hdf5",
                    chunks=2,
                ),
            },
        )
        assert "snap-99" in source.datasets
        assert source.datasets["snap-99"].chunks == 2

    def test_resolve_dataset(self):
        source = SimulationSource(
            name="TestSim",
            description="Test",
            base_url="https://example.com/data/",
            datasets={
                "snap-99": DatasetInfo(
                    path="snapdir_099/",
                    pattern="snap_099.{chunk}.hdf5",
                    chunks=2,
                ),
            },
        )
        urls = source.resolve("snap-99")
        assert len(urls) == 2
        assert "snap_099.0.hdf5" in urls[0]

    def test_resolve_unknown_dataset_raises(self):
        source = SimulationSource(name="TestSim", description="T", base_url="http://x")
        with pytest.raises(KeyError, match="Unknown dataset"):
            source.resolve("nonexistent")

    def test_resolve_raw_url(self):
        source = SimulationSource(name="TestSim", description="T", base_url="http://x")
        urls = source.resolve("http://example.com/file.hdf5")
        assert urls == ["http://example.com/file.hdf5"]
