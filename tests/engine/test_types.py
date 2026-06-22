"""Tests for engine types."""

import pytest

from cosmo_dl.engine.types import AuthConfig, DownloadResult, FileEntry


class TestDownloadResult:
    def test_create_success_result(self):
        result = DownloadResult(
            url="https://example.com/file.hdf5",
            local_path="/tmp/file.hdf5",
            size=1024 * 1024,
            elapsed=12.5,
            speed=83886.0,
            success=True,
            message="OK",
        )
        assert result.success is True
        assert result.size == 1048576
        assert result.speed == pytest.approx(83886.0, rel=0.1)

    def test_create_failed_result(self):
        result = DownloadResult(
            url="https://example.com/file.hdf5",
            local_path="/tmp/file.hdf5",
            size=0,
            elapsed=0.0,
            speed=0.0,
            success=False,
            message="404 Not Found",
        )
        assert result.success is False
        assert result.message == "404 Not Found"


class TestFileEntry:
    def test_file_entry_creation(self):
        entry = FileEntry(
            url="https://host/data/snap.hdf5",
            name="snap.hdf5",
            size=524288000,
            type="file",
            modified="2024-01-15 10:30",
        )
        assert entry.name == "snap.hdf5"
        assert entry.type == "file"
        assert entry.size == 524288000

    def test_dir_entry_creation(self):
        entry = FileEntry(
            url="https://host/data/snapdir/",
            name="snapdir/",
            size=None,
            type="dir",
            modified=None,
        )
        assert entry.type == "dir"
        assert entry.size is None


class TestAuthConfig:
    def test_basic_auth(self):
        auth = AuthConfig(type="basic", username="user", password="pass")
        assert auth.type == "basic"
        assert auth.username == "user"

    def test_bearer_auth(self):
        auth = AuthConfig(type="bearer", token="abc123")
        assert auth.type == "bearer"
        assert auth.token == "abc123"

    def test_no_auth(self):
        auth = AuthConfig(type="none")
        assert auth.type == "none"
