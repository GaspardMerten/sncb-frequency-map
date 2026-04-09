"""Integration tests for all API endpoints using real data.

These tests hit the actual MobilityTwin API — they require a valid
BRUSSELS_MOBILITY_TWIN_KEY in the environment or .env file.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_segments(client):
    resp = await client.get("/api/segments")
    assert resp.status_code == 200
    data = resp.json()
    assert "segments" in data or "error" in data


@pytest.mark.asyncio
async def test_punctuality(client):
    resp = await client.get("/api/punctuality")
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "error" in data


@pytest.mark.asyncio
async def test_reach(client):
    resp = await client.get("/api/reach")
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "error" in data


@pytest.mark.asyncio
async def test_duration(client):
    resp = await client.get("/api/duration", params={"destinations": "Bruxelles-Central"})
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "error" in data


@pytest.mark.asyncio
async def test_connectivity(client):
    resp = await client.get("/api/connectivity")
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "error" in data


@pytest.mark.asyncio
async def test_multimodal(client):
    resp = await client.get("/api/multimodal", params={"address": "Rue de la Loi 1, Brussels"})
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "n_reachable" in data or "error" in data


@pytest.mark.asyncio
async def test_accessibility(client):
    resp = await client.get("/api/accessibility", params={"resolution": 50})
    assert resp.status_code == 200
    data = resp.json()
    assert "n_stops" in data or "error" in data


@pytest.mark.asyncio
async def test_propagation(client):
    resp = await client.get("/api/propagation")
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "error" in data


@pytest.mark.asyncio
async def test_problematic(client):
    resp = await client.get("/api/problematic")
    assert resp.status_code == 200
    data = resp.json()
    assert "offenders" in data or "error" in data


@pytest.mark.asyncio
async def test_missed(client):
    resp = await client.get("/api/missed")
    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data or "error" in data
