"""BE-09 moved the material correction out of the two reverse routes into
`reverse_material_record`, which those routes and draft rejection share.
These lock its behaviour: the offsetting record and movement, never an edit
of the original; 404 for an unknown record; 409 when already corrected; the
caller's authorization check runs before anything is written."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import HTTPException

from mesiri.domains.materials import router as materials

ORG = uuid.uuid4()
USER = uuid.uuid4()
RECORD = uuid.uuid4()
ORIGINAL = {
    "project_id": uuid.uuid4(),
    "site_id": uuid.uuid4(),
    "material_name": "Cement",
    "quantity": 50,
    "unit": "bag",
    "unit_id": uuid.uuid4(),
    "material_id": uuid.uuid4(),
}


class _Conn:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))


@pytest.fixture
def world(monkeypatch):
    state = {"original": dict(ORIGINAL), "reversal_of": None, "movements": [], "events": []}

    class _Repo:
        def __init__(self, conn):
            pass

        async def get_receipt(self, org, record_id):
            return state["original"]

        async def get_usage(self, org, record_id):
            return state["original"]

        async def find_reversal_of(self, org, record_id):
            return state["reversal_of"]

    class _Movements:
        def __init__(self, conn):
            pass

        async def get_by_source(self, source_type, source_id):
            return {"id": "original-movement"}

    async def post_material_movement(conn, **kwargs):
        state["movements"].append(kwargs)

    async def publish(conn, **kwargs):
        state["events"].append(kwargs)

    monkeypatch.setattr(materials, "PostgresMaterialReadRepository", _Repo)
    monkeypatch.setattr(materials, "MaterialMovementsRepository", _Movements)
    monkeypatch.setattr(materials, "post_material_movement", post_material_movement)
    monkeypatch.setattr(materials, "_publish_outbox_event", publish)
    return state


async def _reverse(conn, kind, **kwargs):
    return await materials.reverse_material_record(
        conn,
        kind=kind,
        record_id=RECORD,
        organization_id=ORG,
        user_id=USER,
        reason_note="wrong site",
        occurred_date=datetime.date(2026, 10, 13),
        **kwargs,
    )


async def test_reversing_a_receipt_records_an_adjustment_out_and_an_issue_movement(world):
    conn = _Conn()

    row_id = await _reverse(conn, "receipt")

    [(sql, params)] = conn.calls
    assert "INSERT INTO material_usage" in sql and "'ADJUSTMENT_OUT'" in sql
    assert params["reverses_movement_id"] == RECORD
    assert params["notes"] == "wrong site" and params["created_by"] == USER
    [movement] = world["movements"]
    assert movement["movement_type"] == "ISSUE"
    assert movement["source_id"] == row_id
    assert movement["reversal_of_movement_id"] == "original-movement"
    assert world["events"][0]["event_type"] == "MaterialMovementCorrected"


async def test_reversing_a_usage_records_an_adjustment_in_and_a_receipt_movement(world):
    conn = _Conn()

    await _reverse(conn, "usage")

    [(sql, _)] = conn.calls
    assert "INSERT INTO material_receipts" in sql and "'ADJUSTMENT_IN'" in sql
    assert world["movements"][0]["movement_type"] == "RECEIPT"


async def test_an_unknown_record_is_404(world):
    world["original"] = None
    with pytest.raises(HTTPException) as exc:
        await _reverse(_Conn(), "receipt")
    assert exc.value.status_code == 404


async def test_an_already_corrected_record_is_409_and_nothing_is_written(world):
    world["reversal_of"] = {"occurred_date": "2026-10-12"}
    conn = _Conn()
    with pytest.raises(HTTPException) as exc:
        await _reverse(conn, "usage")
    assert exc.value.status_code == 409
    assert conn.calls == [] and world["movements"] == []


async def test_the_callers_authorization_runs_first(world):
    def deny(original):
        raise HTTPException(status_code=403, detail="no")

    conn = _Conn()
    with pytest.raises(HTTPException) as exc:
        await _reverse(conn, "receipt", authorize=deny)
    assert exc.value.status_code == 403
    assert conn.calls == []
