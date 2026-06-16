"""Tests for the public Python API."""
import pytest
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
    def test_explore_url(self, httpx_mock):
        html = """
        <html><body>
        <a href="file1.hdf5">file1.hdf5</a>
        <a href="file2.hdf5">file2.hdf5</a>
        </body></html>
        """
        httpx_mock.add_response(
            url="https://example.com/data/",
            html=html,
        )
        files = explore("https://example.com/data/", recursive=False)
        assert len(files) == 2
        assert all(isinstance(f, FileEntry) for f in files)
        names = {f.name for f in files}
        assert names == {"file1.hdf5", "file2.hdf5"}


class TestDownload:
    def test_download_url(self, httpx_mock, tmp_path):
        content = b"test data" * 100
        httpx_mock.add_response(
            url="https://example.com/test.hdf5",
            content=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "test.hdf5"
        result = download("https://example.com/test.hdf5", dest, workers=1)
        assert isinstance(result, DownloadResult)
        assert result.success is True
        assert dest.read_bytes() == content

    @pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
    def test_download_source_dataset(self, httpx_mock, tmp_path):
        content = b"fire data"
        httpx_mock.add_response(
            url="https://users.flatironinstitute.org/~mgrudic/fire2_public_release/core/m11i_res7100/output/",
            html="<html><body><a href='snap.hdf5'>snap.hdf5</a></body></html>",
        )
        from cosmo_dl.api import _resolve_target
        urls = _resolve_target("FIRE/m11i_res7100")
        assert len(urls) > 0
        assert urls[0].startswith("https://")
