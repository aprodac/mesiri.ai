"""What people asked Mesiri for and what happened to it, for the control panel (TM-19).

The list lives in the team bot's request log (teammate/listener, SQLite on the same server):
every request, who asked (name, role, company; never a phone number), its stage (asked,
waiting for an ok, building, live, verified, broken, dropped), the commit, the live check
and whether the person used Mesiri again after it went live. This router only reads it,
server-side, with the bot's API token (MESIRI_TEAMMATE_API_TOKEN, set by the deploy); the
token never reaches the browser. Gated by require_platform_admin.

One router, mounted by both apps (backend http/app.py and the assistant's runtime/lifecycle.py),
like the other admin routers.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

STAGES = ("asked", "waiting", "building", "live", "verified", "broken", "dropped")
TIMEOUT_SECONDS = 5.0
#: The fields the page shows; anything else the bot stores (e.g. the watch's sender pseudonym) stays out.
FIELDS = (
    "id", "chat_name", "project", "type", "title", "summary", "status", "stage", "done_ref", "created_by",
    "created_at", "updated_at", "asked_by", "asked_ref", "held", "started_at", "pushed_at", "live_at", "verified",
    "verified_at", "tried_at",
)
#: TM-27: the stages of a request, in order, and their names on the page.
STAGE_STAMPS = (("created_at", "started_at", "plan"), ("started_at", "pushed_at", "build"), ("pushed_at", "live_at", "deploy"))


def _source() -> tuple[str, str]:
    from mesiri.bootstrap.settings import get_settings

    settings = get_settings()
    secret = settings.teammate_api_token
    token = secret.get_secret_value().strip() if secret is not None else ""
    if not token:
        raise HTTPException(
            status_code=503,
            detail="The request log is not connected (MESIRI_TEAMMATE_API_TOKEN is not set on the server).",
        )
    return settings.teammate_api_url.rstrip("/"), token


async def _get(path: str, params: dict[str, str]) -> dict[str, Any]:
    url, token = _source()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            res = await client.get(f"{url}{path}", params=params, headers={"authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"The team bot's request log did not answer ({type(exc).__name__}).") from exc
    if res.status_code == 404:
        raise HTTPException(status_code=404, detail="No such request.")
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"The team bot's request log answered HTTP {res.status_code}.")
    return res.json()


def _public(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item.get(k) for k in FIELDS}
    out["stage"] = out["stage"] if out["stage"] in STAGES else "asked"
    return out


def counts(items: list[dict[str, Any]]) -> dict[str, int]:
    """Requests per stage, plus the totals the page leads with."""
    by = {stage: 0 for stage in STAGES}
    for item in items:
        by[item["stage"]] = by.get(item["stage"], 0) + 1
    return {
        **by,
        "total": len(items),
        "from_users": sum(1 for i in items if i.get("asked_by")),
        "shipped": by["live"] + by["verified"] + by["broken"],
        "open": by["asked"] + by["waiting"] + by["building"],
        "tried": sum(1 for i in items if i.get("tried_at")),
    }


def _when(value: Any) -> dt.datetime | None:
    try:
        when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1)


def loop_numbers(items: list[dict[str, Any]]) -> dict[str, Any]:
    """TM-23: how fast and how well the loop works, for requests people made: hours from asked to live
    (median and slowest tenth), and how the bot's own live check came out."""
    hours = []
    for item in items:
        if not item.get("asked_by"):
            continue
        asked, live = _when(item.get("created_at")), _when(item.get("live_at"))
        if asked and live and live >= asked:
            hours.append((live - asked).total_seconds() / 3600)
    checked = [i for i in items if i.get("verified") in ("ok", "broken")]
    stages: dict[str, float | None] = {}
    for start, end, name in STAGE_STAMPS:  # TM-27: where the time goes, median minutes per stage
        spans = []
        for item in items:
            a, b = _when(item.get(start)), _when(item.get(end))
            if item.get("asked_by") and a and b and b >= a:
                spans.append((b - a).total_seconds() / 60)
        stages[name] = _percentile(spans, 0.5)
    return {
        "minutes_by_stage": stages,
        "shipped_from_users": len(hours),
        "hours_to_live_median": _percentile(hours, 0.5),
        "hours_to_live_p90": _percentile(hours, 0.9),
        "live_checked": len(checked),
        "live_check_ok": sum(1 for i in checked if i.get("verified") == "ok"),
    }


#: TM-21 / TM-23: the person's own verdict on an "it works now" note (journey stage written by the assistant).
VERDICT_SQL = sa.text(
    "SELECT (stage_payload::jsonb)->>'verdict' AS verdict, count(*) AS n FROM journey_traces "
    "WHERE stage = 'release_feedback' AND created_at > :since GROUP BY 1"
)


async def verdicts(conn: AsyncConnection, days: int = 30) -> dict[str, int] | None:
    """Works / Still wrong taps in the last ``days`` days; None when they cannot be read."""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    try:
        rows = (await conn.execute(VERDICT_SQL, {"since": since})).all()
    except Exception:  # noqa: BLE001 -- the page still shows the request log
        _log.warning("requests.verdicts_unreadable", exc_info=True)
        return None
    by = {str(r.verdict): int(r.n) for r in rows}
    return {"works": by.get("works", 0), "still_wrong": by.get("still_wrong", 0), "days": days}


async def _all_items(project: str) -> list[dict[str, Any]]:
    """The one fetch of a project's request log, shared by the admin list and the person's own list."""
    data = await _get("/items", {"project": project})
    return [_public(i) for i in data.get("items", [])]


@router.get("/requests")
async def list_requests(
    project: str = Query("mesiri", max_length=40, pattern=r"^[a-z0-9_-]+$"),
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Every request of the project, newest first, with counts per stage and the loop's numbers (TM-23)."""
    items = await _all_items(project)
    loop = {**loop_numbers(items), "verdicts": await verdicts(conn)}
    return {"project": project, "counts": counts(items), "loop": loop, "items": items}


@router.get("/requests/{item_id}")
async def get_request(
    item_id: int,
    project: str = Query("mesiri", max_length=40, pattern=r"^[a-z0-9_-]+$"),
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """One request with its history (every status change, note and commit)."""
    data = await _get(f"/items/{item_id}", {"project": project})
    item = data.get("item") or {}
    log = [{k: e.get(k) for k in ("at", "status", "ref", "note")} for e in item.get("log", [])]
    return {**_public(item), "log": log}
