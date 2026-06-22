"""Tests for URLExplorer."""

import responses

from cosmo_dl.engine.explorer import FileEntry, URLExplorer

APACHE_LISTING = """
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html><head><title>Index of /data</title></head>
<body>
<h1>Index of /data</h1>
<pre>
<img src="/icons/blank.gif" alt="Icon "> <a href="?C=N;O=D">Name</a>
<img src="/icons/folder.gif" alt="[DIR]"> <a href="snapdir_127/">snapdir_127/</a>
<img src="/icons/folder.gif" alt="[DIR]"> <a href="groups_127/">groups_127/</a>
<img src="/icons/unknown.gif" alt="[   ]"> <a href="README.txt">README.txt</a>
<img src="/icons/hdf.gif" alt="[   ]"> <a href="snapshot_127.0.hdf5">snapshot_127.0.hdf5</a>
</pre>
</body></html>
"""

NGINX_LISTING = """
<html><head><title>Index of /data/</title></head>
<body>
<h1>Index of /data/</h1><hr>
<pre>
<a href="../">../</a>
<a href="snap_099/">snap_099/</a>                                 08-Mar-2024 10:00       -
<a href="snap_099.0.hdf5">snap_099.0.hdf5</a>                            08-Mar-2024 10:00  524288000
<a href="snap_099.1.hdf5">snap_099.1.hdf5</a>                            08-Mar-2024 10:00  524288000
<a href="checksums.md5">checksums.md5</a>                              08-Mar-2024 10:00       1234
</pre><hr></body></html>
"""

TNG_GROUP_RESPONSE = {
    "files": [
        "http://www.tng-project.org/api/TNG50-1/files/groupcat-99/fof_subhalo_tab_099.0.hdf5",
        "http://www.tng-project.org/api/TNG50-1/files/groupcat-99/fof_subhalo_tab_099.1.hdf5",
    ],
    "count": 2,
}


class TestFileEntry:
    def test_file_entry_defaults(self):
        entry = FileEntry(url="https://h/f", name="f")
        assert entry.type == "file"
        assert entry.size is None
        assert entry.modified is None


class TestExplorerParseHtml:
    def test_parse_apache_listing(self):
        explorer = URLExplorer()
        entries = explorer._parse_html("https://host/data/", APACHE_LISTING)

        names = {e.name for e in entries}
        assert "snapdir_127/" in names
        assert "groups_127/" in names
        assert "README.txt" in names
        assert "snapshot_127.0.hdf5" in names

        for e in entries:
            if e.name.endswith("/"):
                assert e.type == "dir"
            else:
                assert e.type == "file"

    def test_parse_nginx_listing(self):
        explorer = URLExplorer()
        entries = explorer._parse_html("https://host/data/", NGINX_LISTING)

        names = {e.name for e in entries}
        assert "snap_099/" in names
        assert "snap_099.0.hdf5" in names
        assert "snap_099.1.hdf5" in names
        assert "checksums.md5" in names

    def test_parse_resolves_full_urls(self):
        explorer = URLExplorer()
        entries = explorer._parse_html("https://host/data/", APACHE_LISTING)

        for e in entries:
            assert e.url.startswith("https://host/data/")

    def test_parse_extracts_sizes_from_nginx(self):
        explorer = URLExplorer()
        entries = explorer._parse_html("https://host/data/", NGINX_LISTING)

        snap0 = next(e for e in entries if e.name == "snap_099.0.hdf5")
        assert snap0.size == 524288000
        assert snap0.type == "file"


class TestExplorerFilter:
    @responses.activate
    def test_include_filter(self):
        responses.add(
            responses.GET,
            "https://host/data/",
            body=APACHE_LISTING,
            headers={"Content-Type": "text/html"},
        )
        explorer = URLExplorer()
        result = explorer.explore("https://host/data/", recursive=False, include="*.hdf5")
        names = {e.name for e in result}
        assert "snapshot_127.0.hdf5" in names
        assert "README.txt" not in names

    @responses.activate
    def test_exclude_filter(self):
        responses.add(
            responses.GET,
            "https://host/data/",
            body=APACHE_LISTING,
            headers={"Content-Type": "text/html"},
        )
        explorer = URLExplorer()
        result = explorer.explore("https://host/data/", recursive=False, exclude="*.txt")
        names = {e.name for e in result}
        assert "README.txt" not in names
        assert "snapshot_127.0.hdf5" in names


class TestExplorerParseJson:
    def test_parse_tng_style_json(self):
        """Parse the IllustrisTNG API format: {'files': ['url1', 'url2', ...]}"""
        explorer = URLExplorer()
        entries = explorer._parse_json(
            "http://www.tng-project.org/api/TNG50-1/files/groupcat-99/",
            TNG_GROUP_RESPONSE,
        )
        assert len(entries) == 2
        assert all(e.type == "file" for e in entries)
        names = {e.name for e in entries}
        assert "fof_subhalo_tab_099.0.hdf5" in names
        assert "fof_subhalo_tab_099.1.hdf5" in names
        for e in entries:
            assert e.url.startswith("http://www.tng-project.org/")

    @responses.activate
    def test_json_explore_integration(self):
        """Full explore() flow with a JSON API response."""
        responses.add(
            responses.GET,
            "http://www.tng-project.org/api/TNG50-1/files/groupcat-99/",
            json=TNG_GROUP_RESPONSE,
            headers={"Content-Type": "application/json"},
        )
        explorer = URLExplorer()
        result = explorer.explore(
            "http://www.tng-project.org/api/TNG50-1/files/groupcat-99/",
            recursive=False,
        )
        assert len(result) == 2
        assert result[0].name == "fof_subhalo_tab_099.0.hdf5"
        assert result[1].name == "fof_subhalo_tab_099.1.hdf5"
