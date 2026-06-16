"""URLExplorer: HTML directory listing parser for discovering files at HTTP URLs."""
from __future__ import annotations

import re
from fnmatch import fnmatch
from urllib.parse import urljoin

import httpx

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
        When *None*, ad-hoc ``httpx.get`` calls are used.
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
        """Fetch *url*, parse its HTML directory listing, and return matching entries.

        Parameters
        ----------
        url : str
            Base URL pointing to an HTML directory listing.
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
        html = self._fetch_page(url)
        if html is None:
            return []

        entries = self._parse_html(url, html)
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

    def _fetch_page(self, url: str) -> str | None:
        """Fetch *url* and return its HTML text, or ``None`` on failure."""
        try:
            if self._session is not None:
                resp = self._session.get(url)
            else:
                resp = httpx.get(url, follow_redirects=True)
            resp.raise_for_status()
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

    @staticmethod
    def _matches_filter(name: str, include: str, exclude: str | None) -> bool:
        """Return ``True`` if *name* satisfies the include/exclude globs."""
        if not fnmatch(name, include):
            return False
        if exclude is not None and fnmatch(name, exclude):
            return False
        return True
