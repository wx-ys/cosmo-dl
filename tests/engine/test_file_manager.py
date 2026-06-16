"""Tests for FileManager."""
import hashlib
import os
import tempfile
from pathlib import Path
import pytest
from cosmo_dl.engine.file_manager import FileManager


class TestMirrorPath:
    def test_strips_base_url_prefix(self):
        result = FileManager.mirror_path(
            url="https://host/data/sims/TNG/snap.hdf5",
            base_url="https://host/data/",
            local_root="/tmp/downloads",
        )
        assert result == Path("/tmp/downloads/sims/TNG/snap.hdf5")

    def test_base_url_without_trailing_slash(self):
        result = FileManager.mirror_path(
            url="https://host/data/sims/snap.hdf5",
            base_url="https://host/data",
            local_root="/tmp/dl",
        )
        assert result == Path("/tmp/dl/sims/snap.hdf5")

    def test_url_not_under_base_raises(self):
        with pytest.raises(ValueError, match="not under base URL"):
            FileManager.mirror_path(
                url="https://other.com/file.hdf5",
                base_url="https://host/data/",
                local_root="/tmp",
            )

    def test_default_local_root(self, monkeypatch):
        monkeypatch.setattr(os, "getcwd", lambda: "/home/user")
        result = FileManager.mirror_path(
            url="https://host/data/file.hdf5",
            base_url="https://host/data/",
        )
        assert result == Path("/home/user/cosmo-dl-downloads/file.hdf5")


class TestCheckIntegrity:
    def test_size_match(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        assert FileManager.check_integrity(f, expected_size=11) is True

    def test_size_mismatch(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        assert FileManager.check_integrity(f, expected_size=100) is False

    def test_sha256_match(self, tmp_path):
        content = b"verify me"
        expected = hashlib.sha256(content).hexdigest()
        f = tmp_path / "test.bin"
        f.write_bytes(content)
        assert FileManager.check_integrity(f, expected_hash=f"sha256:{expected}") is True

    def test_md5_match(self, tmp_path):
        content = b"verify me"
        expected = hashlib.md5(content).hexdigest()
        f = tmp_path / "test.bin"
        f.write_bytes(content)
        assert FileManager.check_integrity(f, expected_hash=f"md5:{expected}") is True

    def test_hash_mismatch(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"wrong content")
        assert FileManager.check_integrity(f, expected_hash="sha256:abc123") is False

    def test_unknown_hash_algo(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"x")
        with pytest.raises(ValueError, match="Unknown hash algorithm"):
            FileManager.check_integrity(f, expected_hash="blake3:abc")

    def test_no_checks_requested(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"x")
        assert FileManager.check_integrity(f) is True

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.bin"
        assert FileManager.check_integrity(f, expected_size=100) is False


class TestGetPartialSize:
    def test_existing_file(self, tmp_path):
        f = tmp_path / "partial.bin"
        f.write_bytes(b"x" * 500)
        assert FileManager.get_partial_size(f) == 500

    def test_missing_file(self, tmp_path):
        assert FileManager.get_partial_size(tmp_path / "nope.bin") == 0

    def test_part_file(self, tmp_path):
        f = tmp_path / "data.hdf5.part"
        f.write_bytes(b"x" * 1024)
        assert FileManager.get_partial_size(f) == 1024
