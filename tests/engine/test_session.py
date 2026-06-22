"""Tests for Session."""

import requests
import responses

from cosmo_dl.engine.session import Session
from cosmo_dl.engine.types import AuthConfig


class TestSession:
    def test_default_session(self):
        session = Session()
        assert session.timeout == 10
        assert session.read_timeout == 300
        assert session.retry == 5
        assert session._client is not None
        assert isinstance(session._client, requests.Session)

    def test_custom_timeout(self):
        session = Session(timeout=60)
        assert session.timeout == 60

    def test_basic_auth(self):
        session = Session(auth=AuthConfig(type="basic", username="u", password="p"))
        assert session._client.auth is not None

    def test_bearer_auth_sets_header(self):
        session = Session(auth=AuthConfig(type="bearer", token="tok123"))
        headers = dict(session._client.headers)
        assert headers.get("Authorization") == "Bearer tok123"

    def test_api_key_auth_sets_header(self):
        session = Session(auth=AuthConfig(type="api-key", token="tng-key-123"))
        headers = dict(session._client.headers)
        assert headers.get("api-key") == "tng-key-123"

    def test_custom_headers(self):
        session = Session(headers={"X-Custom": "value"})
        headers = dict(session._client.headers)
        assert headers.get("X-Custom") == "value"

    def test_proxy(self):
        session = Session(proxy="http://proxy:8080")
        assert session._client.proxies.get("http") == "http://proxy:8080"
        assert session._client.proxies.get("https") == "http://proxy:8080"

    def test_close(self):
        session = Session()
        session.close()
        assert session.is_closed

    def test_context_manager(self):
        with Session() as session:
            assert session._client is not None
        assert session.is_closed

    @responses.activate
    def test_head_request(self):
        responses.add(
            responses.HEAD,
            "https://example.com/file.hdf5",
            headers={"Content-Length": "1048576"},
        )
        session = Session()
        response = session.head("https://example.com/file.hdf5")
        assert response.headers["Content-Length"] == "1048576"

    @responses.activate
    def test_get_with_range(self):
        responses.add(
            responses.GET,
            "https://example.com/file.hdf5",
            body=b"x" * 1024,
            headers={"Content-Range": "bytes 0-1023/1048576"},
        )
        session = Session()
        response = session.get("https://example.com/file.hdf5", headers={"Range": "bytes=0-1023"})
        assert len(response.content) == 1024
