"""Integration tests for cosmo-dl end-to-end workflows."""
import pytest
from click.testing import CliRunner
from cosmo_dl.cli.main import cli
from cosmo_dl.api import download, explore, list_sources


class TestEndToEndDownload:
    def test_download_single_file(self, httpx_mock, tmp_path):
        """Full flow: download a single file via the API."""
        content = b"integration test data" * 500
        httpx_mock.add_response(
            url="https://example.com/sim/data.hdf5",
            content=content,
            headers={"Content-Length": str(len(content))},
        )
        result = download(
            "https://example.com/sim/data.hdf5",
            dest=tmp_path / "data.hdf5",
            workers=1,
        )
        assert result.success is True
        assert (tmp_path / "data.hdf5").read_bytes() == content

    def test_download_with_explore(self, httpx_mock, tmp_path):
        """Full flow: explore then download."""
        listing = """
        <html><body>
        <h1>Index of /data</h1>
        <a href="file_a.hdf5">file_a.hdf5</a>
        <a href="file_b.hdf5">file_b.hdf5</a>
        </body></html>
        """
        httpx_mock.add_response(
            url="https://example.com/data/",
            html=listing,
        )
        httpx_mock.add_response(
            url="https://example.com/data/file_a.hdf5",
            content=b"A" * 1000,
            headers={"Content-Length": "1000"},
        )
        httpx_mock.add_response(
            url="https://example.com/data/file_b.hdf5",
            content=b"B" * 2000,
            headers={"Content-Length": "2000"},
        )

        files = explore("https://example.com/data/", recursive=False)
        assert len(files) == 2

        for entry in files:
            dest = tmp_path / entry.name
            result = download(entry.url, dest=dest, workers=1)
            assert result.success is True

    def test_cli_full_help_chain(self):
        """Verify CLI commands all load without error."""
        runner = CliRunner()
        for cmd in ["download", "explore", "source"]:
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0

    def test_registry_resolve_workflow(self):
        """Verify source -> URL resolution works end-to-end."""
        from cosmo_dl.registry.registry import Registry
        reg = Registry()
        urls = reg.resolve("FIRE/m11i_res7100")
        assert len(urls) > 0
        for url in urls:
            assert url.startswith("https://")


class TestErrorHandling:
    def test_download_404_returns_failure(self, httpx_mock, tmp_path):
        httpx_mock.add_response(
            url="https://example.com/missing.hdf5",
            status_code=404,
        )
        result = download(
            "https://example.com/missing.hdf5",
            dest=tmp_path / "missing.hdf5",
            workers=1,
        )
        assert result.success is False

    def test_explore_bad_url_returns_empty(self, httpx_mock):
        httpx_mock.add_response(
            url="https://bad.example.com/",
            status_code=500,
        )
        files = explore("https://bad.example.com/")
        assert files == []
