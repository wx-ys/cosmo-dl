"""FileManager: mirror path construction, integrity checks, and partial-size queries."""

import hashlib
import os
from pathlib import Path


class FileManager:
    """Static methods for file-mirroring, integrity verification, and partial-download support."""

    @staticmethod
    def mirror_path(url: str, base_url: str, local_root: str | None = None) -> Path:
        """Construct the local filesystem path that mirrors a remote *url*.

        The *base_url* prefix is stripped from *url* and the remainder appended
        to *local_root* (defaults to ``./cosmo-dl-downloads/`` relative to cwd).
        Raises ``ValueError`` when *url* is not under *base_url*.
        """
        # Normalise so base_url always ends with a single slash for safe prefix checks.
        normalized_base = base_url.rstrip("/") + "/"
        if not url.startswith(normalized_base):
            raise ValueError(f"URL {url!r} is not under base URL {base_url!r}")

        relative = url[len(normalized_base) :]

        if local_root is None:
            local_root = os.path.join(os.getcwd(), "cosmo-dl-downloads")

        return Path(local_root) / relative

    @staticmethod
    def _hash_file(path: Path, algorithm: str) -> str:
        """Return the hex digest of *path* computed with the given *algorithm* (e.g. ``"sha256"``)."""
        h = hashlib.new(algorithm)
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def check_integrity(
        path: Path,
        expected_size: int | None = None,
        expected_hash: str | None = None,
    ) -> bool:
        """Verify local-file integrity.

        Returns ``True`` if all requested checks pass, ``False`` otherwise.

        *expected_size* – file size in bytes.
        *expected_hash* – string in ``"algo:hexdigest"`` form (e.g. ``"sha256:abc123"``
          or ``"md5:def456"``). Raises ``ValueError`` for unknown algorithms.
        """
        if not path.is_file():
            return False

        if expected_size is not None and path.stat().st_size != expected_size:
            return False

        if expected_hash is not None:
            if ":" not in expected_hash:
                raise ValueError(f"Malformed hash spec {expected_hash!r}; expected algo:hexdigest")

            algo, _, digest = expected_hash.partition(":")

            try:
                file_digest = FileManager._hash_file(path, algo)
            except ValueError as exc:
                # hashlib.new raises ValueError for unknown algorithms
                raise ValueError(f"Unknown hash algorithm: {algo}") from exc

            if file_digest != digest:
                return False

        return True

    @staticmethod
    def get_partial_size(path: Path) -> int:
        """Return the size in bytes of *path* or its ``.part`` variant, or 0 if neither exists."""
        candidate_direct = Path(path)
        if candidate_direct.is_file():
            return candidate_direct.stat().st_size

        candidate_part = Path(str(path) + ".part")
        if candidate_part.is_file():
            return candidate_part.stat().st_size

        return 0
