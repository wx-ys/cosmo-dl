"""URLExplorer: HTML directory listing + JSON API parser for discovering files at HTTP URLs."""
from __future__ import annotations

import re
from fnmatch import fnmatch
from urllib.parse import urljoin

import requests

from cosmo_dl.engine.session import Session
from cosmo_dl.engine.types import FileEntry

# Regex to extract <a href="...">text</a> plus trailing line content (for Nginx sizes)
_A_TAG_RE = re.compile(
    r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>(.*)',
    re.IGNORECASE,
)

# Href prefixes that should never be followed
_SKIP_HREF_PREFIXES = ("#", "?", "javascript:", "mailto:")

# Link text / names that should be skipped (parent dir, self, etc.)
_SKIP_NAMES = ("..", ".", "../")

# Regex to strip HTML tags from link text to get a clean name
_STRIP_TAGS_RE = re.compile(r"<[^>]*>")


class URLExplorer:
    """Discover files by parsing HTML directory listings from HTTP servers.

    Parameters
    ----------
    session : Session or None
        Optional cosmo-dl Session for authenticated / configured requests.
        When *None*, ad-hoc ``requests.get`` calls are used.
    """

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explore(
        self,
        url: str,
        *,
        recursive: bool = True,
        max_depth: int | None = None,
        include: str = "*",
        exclude: str | None = None,
    ) -> list[FileEntry]:
        """Fetch *url*, parse its listing, and return matching entries.

        Supports both HTML directory listings and JSON API responses (e.g.,
        the IllustrisTNG API which returns ``{"files": ["...", ...]}``).

        Parameters
        ----------
        url : str
            Base URL pointing to an HTML directory listing or JSON API endpoint.
        recursive : bool
            When ``True`` (default), recurse into sub-directories.
        max_depth : int or None
            Maximum recursion depth.  ``None`` means unlimited.
        include : str
            ``fnmatch``-style glob for names to *include* (default ``"*"``).
        exclude : str or None
            ``fnmatch``-style glob for names to *exclude*.

        Returns
        -------
        list[FileEntry]
            List of matching file and directory entries.
        """
        page = self._fetch_page(url)
        if page is None:
            return []

        if isinstance(page, dict):
            entries = self._parse_json(url, page)
        else:
            entries = self._parse_html(url, page)

        result: list[FileEntry] = []

        for entry in entries:
            # Always recurse into sub-directories (if enabled) so we can
            # discover files nested beneath directories that may not
            # themselves match the filter.
            if entry.type == "dir" and recursive:
                if max_depth is None or max_depth > 0:
                    next_depth = None if max_depth is None else max_depth - 1
                    result.extend(
                        self.explore(
                            entry.url,
                            recursive=True,
                            max_depth=next_depth,
                            include=include,
                            exclude=exclude,
                        )
                    )

            if self._matches_filter(entry.name, include, exclude):
                result.append(entry)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_page(self, url: str) -> dict | str | None:
        """Fetch *url* and return parsed JSON (dict), HTML text, or ``None`` on failure.

        If the response Content-Type contains ``json``, it is parsed as JSON
        and returned as a dict.  Otherwise the raw text is returned (HTML).
        """
        try:
            if self._session is not None:
                resp = self._session.get(url)
            else:
                resp = requests.get(url, timeout=30)
            resp.raise_for_status()

            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                return resp.json()
            return resp.text
        except Exception:
            return None

    def _parse_html(self, base_url: str, html: str) -> list[FileEntry]:
        """Extract ``FileEntry`` items from an HTML directory listing.

        Parameters
        ----------
        base_url : str
            The URL that produced *html* (used to resolve relative links).
        html : str
            Raw HTML of the directory listing page.

        Returns
        -------
        list[FileEntry]
        """
        entries: list[FileEntry] = []

        for match in _A_TAG_RE.finditer(html):
            href = match.group(1)
            raw_name = match.group(2)
            trailing = match.group(3)

            # --- filter unwanted links ------------------------------------
            if any(href.startswith(p) for p in _SKIP_HREF_PREFIXES):
                continue

            # Resolve full URL early so we can use it for checks
            full_url = urljoin(base_url, href)

            # Clean up the display name (strip any HTML tags inside <a>)
            name = _STRIP_TAGS_RE.sub("", raw_name).strip()
            if not name:
                continue

            if name in _SKIP_NAMES:
                continue

            # --- classify ------------------------------------------------
            entry_type: str = "dir" if name.endswith("/") else "file"

            # --- extract size from Nginx-style listing --------------------
            size: int | None = None
            if entry_type == "file" and trailing:
                # Nginx puts date / time / size columns after </a>.
                # The size is the last integer on the line (or "-" for dirs).
                size_match = re.search(r"(\d+)\s*$", trailing)
                if size_match:
                    size = int(size_match.group(1))

            entries.append(
                FileEntry(
                    url=full_url,
                    name=name,
                    size=size,
                    type=entry_type,  # type: ignore[arg-type]
                )
            )

        return entries

    def _parse_json(self, base_url: str, data: dict) -> list[FileEntry]:
        """Extract ``FileEntry`` items from a JSON API response.

        Handles the IllustrisTNG API format where responses contain a
        ``files`` key whose value is a list of file URLs.  Other keys that
        contain URLs or nested structures may be treated as directories.
        """
        entries: list[FileEntry] = []

        # TNG-style: {"files": ["url1", "url2", ...], "count": N}
        if "files" in data and isinstance(data["files"], list):
            for file_url in data["files"]:
                if not isinstance(file_url, str):
                    continue
                name = file_url.rstrip("/").rsplit("/", 1)[-1]
                entries.append(FileEntry(url=file_url, name=name, type="file"))
            return entries

        # Generic JSON: treat string values that look like URLs as files,
        # and nested objects/arrays as directories
        for key, value in data.items():
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                entries.append(FileEntry(url=value, name=key, type="file"))
            elif isinstance(value, (dict, list)):
                # A sub-resource — treat as directory for recursion
                sub_url = base_url.rstrip("/") + "/" + key + "/"
                entries.append(FileEntry(url=sub_url, name=key + "/", type="dir"))

        return entries

    @staticmethod
    def _matches_filter(name: str, include: str, exclude: str | None) -> bool:
        """Return ``True`` if *name* satisfies the include/exclude globs."""
        if not fnmatch(name, include):
            return False
        if exclude is not None and fnmatch(name, exclude):
            return False
        return True
