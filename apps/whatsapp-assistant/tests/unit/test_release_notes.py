"""TM-16: whoever hit a dead end hears, once, that it works now (runtime/release_notes.py)."""

from __future__ import annotations

import datetime as dt
import json
import uuid

from runtime import release_notes as rn

TODAY = dt.date(2026, 10, 29)
ORG, RAVI, ANIL = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
NOTE = {
    "id": "attendance-photo",
    "date": "2026-10-29",
    "for": ["cor_photo_1", "cor_photo_2", "cor_unknown"],
    "message": "Ningal chodicha attendance photo ippo Mesiri-yil und: 'innathe attendance photo ayakku' ennu ayakku.",
}


async def _requester(_conn, cid):  # noqa: ANN001, ANN202
    return {
        "cor_photo_1": rn.Requester(ORG, RAVI),
        "cor_photo_2": rn.Requester(ORG, RAVI),  # the same person tried twice: one message
        "cor_other": rn.Requester(ORG, ANIL),
    }.get(cid)


class _Claims:
    def __init__(self) -> None:
        self.rows: dict[tuple, dict] = {}

    async def __call__(self, **kw):  # noqa: ANN003, ANN204
        key = (kw["organization_id"], kw["rule_key"], kw["subject_id"], kw["occurred_on"])
        if key in self.rows:
            return None  # the UNIQUE key: once
        self.rows[key] = kw
        return uuid.uuid4()


async def test_each_person_a_note_names_gets_it_once():
    claims = _Claims()
    notes = rn.parse_notes({"notes": [NOTE]})

    assert await rn.queue_release_notes(None, today=TODAY, notes=notes, requester=_requester, claim=claims) == 1
    (row,) = claims.rows.values()
    assert row["rule_key"] == "release:attendance-photo" and row["recipient_user_id"] == RAVI
    assert row["payload"] == {"message": NOTE["message"]}
    # The next tick, and every one after: nothing again.
    assert await rn.queue_release_notes(None, today=TODAY, notes=notes, requester=_requester, claim=claims) == 0


async def test_old_notes_are_never_sent_and_bad_ones_are_skipped():
    old = {**NOTE, "id": "old-one", "date": "2026-10-01"}
    bad = [{**NOTE, "id": "Bad Id"}, {**NOTE, "id": "no-people", "for": []}, {**NOTE, "id": "too-long", "message": "x" * 701}, {"id": "x"}]
    notes = rn.parse_notes({"notes": [old, *bad, NOTE]})
    assert [n.id for n in notes] == ["old-one", "attendance-photo"]
    assert [n.id for n in rn.due_notes(notes, TODAY)] == ["attendance-photo"]


def test_the_shipped_notes_file_is_valid(tmp_path):
    shipped = json.loads(rn.NOTES_PATH.read_text(encoding="utf-8"))
    assert isinstance(shipped["notes"], list)
    assert len(rn.parse_notes(shipped)) == len(shipped["notes"])  # every shipped note is valid
    assert rn.load_notes(tmp_path / "missing.json") == []
