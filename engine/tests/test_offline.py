"""Offline: every feature works without the network, and nothing but this PC is ever contacted.

Each connection and name lookup the engine tries is checked; anything that isn't this PC fails the
test. The only downloads RecPro has (AI models, the GPU pack) are refused while Strict offline is on.
"""
from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient

from recpro.api.app import create_app
from recpro.jobs.places import PlacesStage
from tests.conftest import add_and_index
from tests.test_places import gps_photo

LOCAL = {"127.0.0.1", "::1", "localhost", "testserver"}


@pytest.fixture()
def no_network(monkeypatch):
    """Records (and refuses) every attempt to reach anything but this PC."""
    tried: list[str] = []
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def guard(host):
        if isinstance(host, (bytes, bytearray)):
            host = host.decode(errors="replace")
        if isinstance(host, str) and host not in LOCAL and not host.startswith("127."):
            tried.append(host)
            raise OSError(f"offline test: tried to reach {host}")

    def connect(self, addr):
        guard(addr[0] if isinstance(addr, tuple) else addr)
        return real_connect(self, addr)

    def connect_ex(self, addr):
        guard(addr[0] if isinstance(addr, tuple) else addr)
        return real_connect_ex(self, addr)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None:
            guard(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return tried


def test_everything_works_without_the_network(ctx, tmp_path, no_network):
    lib = tmp_path / "Lib"
    gps_photo(lib / "goa.jpg", 15.5439, 73.7553, when="2023:01:14 16:30:00", seed=1)
    gps_photo(lib / "goa-2.jpg", 15.5733, 73.7407, when="2023:01:15 11:00:00", seed=2)
    gps_photo(lib / "pune.jpg", 18.5204, 73.8567, when="2023:01:02 10:00:00", seed=3)
    gps_photo(lib / "pune-2.jpg", 18.5308, 73.8475, when="2023:02:02 10:00:00", seed=4)
    add_and_index(ctx, lib)
    PlacesStage(ctx).process(ctx.db.q("SELECT * FROM media WHERE gps_lat IS NOT NULL"))
    client = TestClient(create_app(ctx))
    h = {"X-RecPro-Token": "test-token", "host": "127.0.0.1"}
    for path in (
        "/api/health", "/api/settings", "/api/stats", "/api/timeline", "/api/folders", "/api/people", "/api/explore",
        "/api/places", "/api/places/clusters", "/api/places/towns?s=15&w=73&n=19&e=74", "/api/places/media?cc=IN",
        "/api/memories", "/api/memories/on-this-day", "/api/cleanup", "/api/cleanup/exact", "/api/answers/export",
        "/api/searches", "/api/ops", "/api/bin",
    ):
        r = client.get(path, headers=h)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
    r = client.post("/api/search", json={"q": "Goa 2023"}, headers=h)
    assert r.status_code == 200 and len(r.json()["sure"]) == 2
    trips = client.get("/api/memories", headers=h).json()["trips"]
    assert [t["name"] for t in trips] == ["Goa"]
    assert no_network == [], f"tried to reach {no_network}"


def test_strict_offline_refuses_every_download(ctx, no_network):
    ctx.settings.update({"privacy.strict_offline": True})
    client = TestClient(create_app(ctx))
    h = {"X-RecPro-Token": "test-token", "host": "127.0.0.1"}
    r = client.post("/api/models/download", json={"ids": []}, headers=h)  # every model for this PC, the GPU pack included
    assert r.status_code == 403 and "Strict offline" in r.json()["detail"]
    assert client.get("/api/health", headers=h).json()["strictOffline"] is True
    assert no_network == []


def test_the_guard_catches_a_real_attempt(no_network):
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 443), timeout=1)
    assert no_network == ["example.com"]
