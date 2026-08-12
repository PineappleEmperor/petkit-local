"""dev_feed_get response must match the cloud's shape exactly."""
import json
import time

from aiohttp.test_utils import TestClient, TestServer

from petkit_local.devices.registry import DeviceRegistry
from petkit_local.http.server import create_app


def _app(device_type="d4sh"):
    reg = DeviceRegistry()
    reg.get_or_create(petkit_id=1, device_type=device_type, serial_number="SN1")
    config = {"api_url": "http://localhost:8080", "bucket_endpoint": "https://localhost:9000"}
    app = create_app(reg, config)
    return app, reg


async def _get_feed(client):
    r = await client.get("/6/d4sh/dev_feed_get",
                         headers={"X-Device": "id=1&nonce=x&timestamp=1&type=d4sh&sign=x"})
    return (await r.json())["result"]


async def test_empty_schedule_has_all_three_keys():
    app, reg = _app()
    async with TestClient(TestServer(app)) as c:
        result = await _get_feed(c)
        assert set(result.keys()) == {"schedule", "nextTick", "latest"}
        assert isinstance(result["schedule"], list)
        assert isinstance(result["nextTick"], int)
        assert isinstance(result["latest"], list)


async def test_recurring_meals_appear_in_latest_as_s_entries():
    """A schedule with it[] items must produce s_ entries in latest with
    countdowns — this is what the cloud does and what was missing."""
    app, reg = _app()
    d = reg.get(1)
    d.config["feed_schedule"] = {
        "schedule": [{"re": "1,2,3,4,5,6,7", "it": [
            {"id": "n_50100", "t": 50100, "a1": 1, "a2": 0},
        ]}],
    }
    async with TestClient(TestServer(app)) as c:
        result = await _get_feed(c)
        assert len(result["latest"]) >= 1
        entry = result["latest"][0]
        assert entry["id"].startswith("s_")
        assert entry["a1"] == 1 and entry["a2"] == 0
        assert 0 < entry["t"] <= 7 * 86400


async def test_recurring_meal_countdown_decreases_over_time():
    """Cloud recomputes t on every poll — two polls show the same entry's t
    dropping. Ours must do the same."""
    app, reg = _app()
    d = reg.get(1)
    now = time.time()
    lt = time.localtime(now)
    secs_since_midnight = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    future_t = secs_since_midnight + 7200
    d.config["feed_schedule"] = {
        "schedule": [{"re": "1,2,3,4,5,6,7", "it": [
            {"id": "n_test", "t": future_t, "a1": 1, "a2": 0},
        ]}],
    }
    async with TestClient(TestServer(app)) as c:
        r1 = await _get_feed(c)
        t1 = r1["latest"][0]["t"]
        assert 7100 < t1 < 7300


async def test_itemJsonString_is_rebuilt_from_it():
    app, reg = _app()
    d = reg.get(1)
    d.config["feed_schedule"] = {
        "schedule": [{"re": "1", "it": [
            {"id": "n_50100", "t": 50100, "a1": 1, "a2": 0},
        ]}],
    }
    async with TestClient(TestServer(app)) as c:
        result = await _get_feed(c)
        group = result["schedule"][0]
        assert "itemJsonString" in group
        assert json.loads(group["itemJsonString"]) == group["it"]


async def test_deferred_feed_appears_in_latest():
    app, reg = _app()
    d = reg.get(1)
    future = time.time() + 3600
    d.config["feed_schedule"] = {
        "schedule": [{"re": "1,2,3,4,5,6,7", "it": []}],
        "deferred": [{"id": "d_20260813_61500", "a1": 0, "a2": 1, "fire_at": future}],
    }
    async with TestClient(TestServer(app)) as c:
        result = await _get_feed(c)
        d_entries = [e for e in result["latest"] if e["id"].startswith("d_")]
        assert len(d_entries) == 1
        assert 3550 < d_entries[0]["t"] < 3650


async def test_expired_deferred_is_pruned():
    app, reg = _app()
    d = reg.get(1)
    d.config["feed_schedule"] = {
        "schedule": [{"re": "1,2,3,4,5,6,7", "it": []}],
        "deferred": [{"id": "d_20260812_10000", "a1": 1, "a2": 0, "fire_at": time.time() - 60}],
    }
    async with TestClient(TestServer(app)) as c:
        result = await _get_feed(c)
        d_entries = [e for e in result["latest"] if e["id"].startswith("d_")]
        assert d_entries == []
        assert d.config["feed_schedule"]["deferred"] == []


async def test_response_shape_matches_cloud():
    """Every key the cloud returns must be present, at every level."""
    app, reg = _app()
    d = reg.get(1)
    future = time.time() + 7200
    d.config["feed_schedule"] = {
        "schedule": [
            {"re": "2,3,4,6,7", "it": []},
            {"re": "1", "it": [
                {"id": "n_50100", "t": 50100, "a1": 1, "a2": 0},
                {"id": "n_71700", "t": 71700, "a1": 1, "a2": 6},
            ]},
        ],
        "deferred": [{"id": "d_20260813_61500", "a1": 0, "a2": 1, "fire_at": future}],
    }
    async with TestClient(TestServer(app)) as c:
        result = await _get_feed(c)
        assert set(result.keys()) == {"schedule", "nextTick", "latest"}
        for group in result["schedule"]:
            assert "re" in group and "it" in group and "itemJsonString" in group
        assert len(result["latest"]) >= 2
        for entry in result["latest"]:
            assert set(entry.keys()) == {"id", "t", "a1", "a2"}
            assert isinstance(entry["t"], int) and entry["t"] > 0
        s_entries = [e for e in result["latest"] if e["id"].startswith("s_")]
        d_entries = [e for e in result["latest"] if e["id"].startswith("d_")]
        assert len(s_entries) >= 1
        assert len(d_entries) == 1
