"""Unit tests for settings and request handling that depend on the hosting setup."""

import pytest
from starlette.requests import Request

from forge.core.config import Settings, settings
from forge.core.rate_limit import client_ip


class TestDatabaseUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "postgres://u:p@host:5432/db",
            "postgresql://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ],
    )
    def test_normalised_to_asyncpg(self, url):
        assert (
            Settings(DATABASE_URL=url).DATABASE_URL
            == "postgresql+asyncpg://u:p@host:5432/db"
        )


def make_request(forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": ("10.0.0.1", 1234)})


class TestClientIp:
    def test_without_header_uses_peer(self):
        assert client_ip(make_request()) == "10.0.0.1"

    def test_one_hop_ignores_client_supplied_entries(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
        assert client_ip(make_request("6.6.6.6, 203.0.113.7")) == "203.0.113.7"

    def test_two_hops(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
        request = make_request("6.6.6.6, 203.0.113.7, 172.16.0.2")
        assert client_ip(request) == "203.0.113.7"

    def test_more_hops_than_entries_uses_leftmost(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 3)
        assert client_ip(make_request("203.0.113.7")) == "203.0.113.7"

    def test_zero_hops_ignores_header(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
        assert client_ip(make_request("203.0.113.7")) == "10.0.0.1"
