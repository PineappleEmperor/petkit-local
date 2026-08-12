"""dev_feed_get — the feeder's scheduled meals.

A feeder dispenses on its own clock, from the schedule it fetches here; the
server is not in the loop at feeding time. So the answer must always be a
well-formed schedule — an unidentified device gets an empty-but-valid one rather
than an error, which leaves it dispensing nothing instead of retrying forever.

``latest[]`` carries upcoming feeds with live countdowns — ``t`` is seconds
from NOW until the feed fires, recomputed on every poll (the cloud does the
same: two polls 40 s apart showed the same entry's ``t`` drop by 39). Three
ID prefixes:

* ``d_YYYYMMDD_SSSSS`` — **deferred**: a one-off feed at a specific date/time.
* ``s_YYYYMMDD_SSSSS`` — **scheduled**: a concrete instance of a recurring meal.
* ``n_SSSSS`` — **normal**: the recurring template in ``schedule[].it[]``.

``nextTick`` is relative seconds until the device should re-poll this endpoint.
"""
from __future__ import annotations

import json
import time

from aiohttp import web

from petkit_local.http.handlers._common import request_device

_DEFAULT_TICK = 7200
_EMPTY_GROUP = {"re": "1,2,3,4,5,6,7", "it": [], "itemJsonString": "[]"}


def _next_occurrence(now: float, day_start_ts: float, t_secs: int,
                     weekdays: list[int], petkit_today: int) -> float | None:
    """Timestamp of the next firing of a recurring meal.

    Checks today (if the time hasn't passed) then the next 7 days, returning
    the first day whose PetKit weekday number is in ``weekdays``.
    """
    for day_offset in range(8):
        candidate_ts = day_start_ts + day_offset * 86400 + t_secs
        if candidate_ts <= now:
            continue
        pk_wd = ((petkit_today - 1 + day_offset) % 7) + 1
        if pk_wd in weekdays:
            return candidate_ts
    return None


def _build_latest(feed: dict, now: float) -> list[dict]:
    """Compute ``latest[]``: next occurrences of recurring meals + deferred.

    The cloud puts BOTH in ``latest``:
    * ``s_YYYYMMDD_SSSSS`` — the next firing of a recurring ``n_`` item
    * ``d_YYYYMMDD_SSSSS`` — a one-off deferred feed

    ``t`` is a live countdown (seconds from now), recomputed every poll.
    """
    result = []

    lt = time.localtime(now)
    day_start_ts = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
    today_weekday = lt.tm_wday  # Monday=0
    petkit_today = (today_weekday + 2) % 7 or 7  # PetKit: Sunday=1..Saturday=7

    for group in feed.get("schedule", []):
        weekday_strs = str(group.get("re", "")).split(",")
        weekdays = [int(x) for x in weekday_strs if x.strip().isdigit()]
        for item in group.get("it", []):
            t_secs = item.get("t", 0)
            fire = _next_occurrence(now, day_start_ts, t_secs,
                                    weekdays, petkit_today)
            if fire is not None:
                countdown = int(fire - now)
                date_str = time.strftime("%Y%m%d", time.localtime(fire))
                result.append({
                    "id": f"s_{date_str}_{t_secs}",
                    "t": countdown,
                    "a1": item.get("a1", 0),
                    "a2": item.get("a2", 0),
                })

    deferred = feed.get("deferred") or []
    remaining = []
    for d in deferred:
        fire_at = d.get("fire_at", 0)
        if fire_at <= now:
            continue
        remaining.append(d)
        result.append({
            "id": d.get("id", ""),
            "t": int(fire_at - now),
            "a1": d.get("a1", 0),
            "a2": d.get("a2", 0),
        })
    if len(remaining) != len(deferred):
        feed["deferred"] = remaining

    result.sort(key=lambda x: x["t"])
    return result


def _compute_next_tick(latest: list[dict]) -> int:
    if not latest:
        return _DEFAULT_TICK
    soonest = min(entry["t"] for entry in latest)
    return max(60, soonest)


async def handle_feed_get(request: web.Request) -> web.Response:
    """Return the device's stored feeding schedule with live countdowns.

    Returns:
        ``{"result": {"schedule": [...], "nextTick": N, "latest": [...]}}``.
        Structure matches the real cloud's response 1:1.
    """
    device = request_device(request)

    if not device or not device.config.get("feed_schedule"):
        return web.json_response({
            "result": {
                "schedule": [_EMPTY_GROUP],
                "nextTick": _DEFAULT_TICK,
                "latest": [],
            }
        })

    feed = device.config["feed_schedule"]
    if not isinstance(feed, dict):
        return web.json_response({"result": feed})

    now = time.time()
    latest = _build_latest(feed, now)
    next_tick = _compute_next_tick(latest)

    for group in feed.get("schedule", []):
        if "it" in group:
            group["itemJsonString"] = json.dumps(
                group["it"], separators=(",", ":"))

    return web.json_response({
        "result": {
            "schedule": feed.get("schedule", [_EMPTY_GROUP]),
            "nextTick": next_tick,
            "latest": latest,
        }
    })
