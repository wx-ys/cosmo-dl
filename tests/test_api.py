"""Tests for the public Python API."""
import pytest
import responses
from cosmo_dl.api import download, explore, list_sources
from cosmo_dl.registry.source import DatasetInfo
from cosmo_dl.engine.types import DownloadResult, FileEntry


class TestListSources:
    def test_list_sources_returns_names(self):
        names = list_sources()
        assert isinstance(names, list)
        assert "FIRE" in names
        assert "Auriga" in names


class TestExplore:
    @responses.activate
    def test_explore_url(self):
        html = """
        <html><body>
        <a href="file1.hdf5">file1.hdf5</a>
        <a href="file2.hdf5">file2.hdf5</a>
        </body></html>
        """
        responses.add(
            responses.GET,
            "https://example.com/data/",
            body=html,
            headers={"Content-Type": "text/html"},
        )
        files = explore("https://example.com/data/", recursive=False)
        assert len(files) == 2
        assert all(isinstance(f, FileEntry) for f in files)
        names = {f.name for f in files}
        assert names == {"file1.hdf5", "file2.hdf5"}


class TestDownload:
    @responses.activate
    def test_download_url(self, tmp_path):
        content = b"test data" * 100
        responses.add(
            responses.GET,
            "https://example.com/test.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "test.hdf5"
        result = download("https://example.com/test.hdf5", dest, workers=1)
        assert isinstance(result, DownloadResult)
        assert result.success is True
        assert dest.read_bytes() == content

    def test_download_source_dataset(self, tmp_path):
        content = b"fire data"
        from cosmo_dl.api import _resolve_target
        urls = _resolve_target("FIRE/m11i_res7100")
        assert len(urls) > 0
        assert urls[0].startswith("https://")
