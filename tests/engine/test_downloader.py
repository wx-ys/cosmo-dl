"""Tests for Downloader."""
import tempfile
from pathlib import Path
import pytest
import responses
from cosmo_dl.engine.downloader import Downloader, MB
from cosmo_dl.engine.session import Session
from cosmo_dl.engine.rate_limiter import RateLimiter
from cosmo_dl.engine.types import DownloadResult


class TestDownloader:
    @responses.activate
    def test_download_small_file(self, tmp_path):
        content = b"hello cosmos" * 100
        responses.add(
            responses.GET,
            "https://example.com/small.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "small.hdf5"
        dl = Downloader()
        result = dl.download("https://example.com/small.hdf5", dest, workers=1)

        assert result.success is True
        assert result.size == len(content)
        assert dest.read_bytes() == content

    @responses.activate
    def test_download_with_expected_hash(self, tmp_path):
        import hashlib
        content = b"verify this file"
        expected = hashlib.sha256(content).hexdigest()

        responses.add(
            responses.GET,
            "https://example.com/verified.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "verified.hdf5"
        dl = Downloader()
        result = dl.download(
            "https://example.com/verified.hdf5", dest,
            workers=1, expected_hash=f"sha256:{expected}",
        )
        assert result.success is True

    @responses.activate
    def test_download_hash_mismatch_fails(self, tmp_path):
        content = b"wrong content"
        responses.add(
            responses.GET,
            "https://example.com/bad.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "bad.hdf5"
        dl = Downloader()
        result = dl.download(
            "https://example.com/bad.hdf5", dest,
            workers=1, expected_hash="sha256:00000000000000000000000000000000",
        )
        assert result.success is False

    @responses.activate
    def test_download_resume_from_partial(self, tmp_path):
        content = b"A" * 5000
        partial_content = content[1000:]

        responses.add(
            responses.GET,
            "https://example.com/resume.hdf5",
            body=partial_content,
            headers={
                "Content-Length": "4000",
                "Content-Range": "bytes 1000-4999/5000",
            },
            match=[responses.matchers.header_matcher({"Range": "bytes=1000-"})],
        )
        dest = tmp_path / "resume.hdf5"
        dest.write_bytes(content[:1000])

        dl = Downloader()
        result = dl.download("https://example.com/resume.hdf5", dest,
                             workers=1, resume=True)
        assert result.success is True
        assert dest.read_bytes() == content

    @responses.activate
    def test_download_creates_parent_dirs(self, tmp_path):
        content = b"nested file"
        responses.add(
            responses.GET,
            "https://example.com/a/b/c/file.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "deep" / "nested" / "file.hdf5"
        dl = Downloader()
        result = dl.download("https://example.com/a/b/c/file.hdf5", dest, workers=1)
        assert result.success is True
        assert dest.exists()

    @responses.activate
    def test_download_result_has_elapsed_and_speed(self, tmp_path):
        content = b"x" * 10000
        responses.add(
            responses.GET,
            "https://example.com/timed.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "timed.hdf5"
        dl = Downloader()
        result = dl.download("https://example.com/timed.hdf5", dest, workers=1)
        assert result.elapsed > 0
        assert result.speed > 0

    @responses.activate
    def test_download_with_rate_limit(self, tmp_path):
        content = b"x" * 5000
        responses.add(
            responses.GET,
            "https://example.com/limited.hdf5",
            body=content,
            headers={"Content-Length": str(len(content))},
        )
        dest = tmp_path / "limited.hdf5"
        limiter = RateLimiter("unlimited")
        dl = Downloader(rate_limiter=limiter)
        result = dl.download("https://example.com/limited.hdf5", dest, workers=1)
        assert result.success is True

    @responses.activate
    def test_404_returns_failure(self, tmp_path):
        responses.add(
            responses.GET,
            "https://example.com/missing.hdf5",
            status=404,
        )
        dest = tmp_path / "missing.hdf5"
        dl = Downloader()
        result = dl.download("https://example.com/missing.hdf5", dest, workers=1)
        assert result.success is False

    def test_mb_constant(self):
        assert MB == 1_048_576
