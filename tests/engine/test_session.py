"""Tests for Session."""
import httpx
import pytest
from cosmo_dl.engine.session import Session
from cosmo_dl.engine.types import AuthConfig


class TestSession:
    def test_default_session(self):
        session = Session()
        assert session.timeout == 30
        assert session.retry == 3
        assert session._client is not None
        assert isinstance(session._client, httpx.Client)

    def test_custom_timeout(self):
        session = Session(timeout=60)
        assert session.timeout == 60

    def test_basic_auth(self):
        session = Session(auth=AuthConfig(type="basic", username="u", password="p"))
        assert session._client.auth is not None

    def test_bearer_auth_sets_header(self):
        session = Session(auth=AuthConfig(type="bearer", token="tok123"))
        headers = dict(session._client.headers)
        assert headers.get("authorization") == "Bearer tok123"

    def test_custom_headers(self):
        session = Session(headers={"X-Custom": "value"})
        headers = dict(session._client.headers)
        assert headers.get("x-custom") == "value"

    def test_proxy(self):
        session = Session(proxy="http://proxy:8080")
        # In httpx 0.28+, proxy is internal to the transport layer.
        # Verify the transport pool is a proxy type.
        pool = session._client._transport._pool
        assert "Proxy" in type(pool).__name__

    def test_close(self):
        session = Session()
        session.close()
        assert session._client.is_closed

    def test_context_manager(self):
        with Session() as session:
            assert session._client is not None
        assert session._client.is_closed

    def test_head_request(self, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/file.hdf5",
            headers={"Content-Length": "1048576"},
        )
        session = Session()
        response = session.head("https://example.com/file.hdf5")
        assert response.headers["Content-Length"] == "1048576"

    def test_get_with_range(self, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/file.hdf5",
            headers={"Content-Range": "bytes 0-1023/1048576"},
            content=b"x" * 1024,
        )
        session = Session()
        response = session.get("https://example.com/file.hdf5",
                               headers={"Range": "bytes=0-1023"})
        assert len(response.content) == 1024
