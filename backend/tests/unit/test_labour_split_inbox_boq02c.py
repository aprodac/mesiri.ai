"""BOQ-02c: labour Mesiri put on BOQ lines by itself (or on no line) is put in front of the people who see the BOQ,
in the "waiting for you" list, one row a project, so a split is confirmed rather than silently trusted."""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

from mesiri.domains.approvals import inbox

PROJECT = uuid.uuid4()


class _Rows:
    def mappings(self):
        return self

    def all(self):
        return [{"id": PROJECT, "name": "Green Villa"}]


class _Conn:
    async def execute(self, *_a, **_k):
        return _Rows()


def _auth(role: str):
    return SimpleNamespace(role=role, organization_id=uuid.uuid4(),
                           project_scope=SimpleNamespace(grants_all_org_projects=True, project_ids=[]))


async def test_a_boq_role_sees_one_row_a_project_with_what_to_confirm(monkeypatch):
    from mesiri.domains.costing import router as costing

    async def labour(**kw):
        assert kw["to_confirm"] is True
        return {"groups": [{"date": "2026-11-13", "auto": True}, {"date": "2026-11-12", "auto": True},
                           {"date": "2026-11-14", "auto": False}]}

    monkeypatch.setattr(costing, "project_labour", labour)
    (item,) = await inbox.labour_splits(_Conn(), _auth("PROJECT_MANAGER"), datetime.date(2026, 11, 15))
    assert item["kind"] == "labour_split" and item["title"] == "Labour on the BOQ: Green Villa"
    assert item["detail"] == "2 put on lines by Mesiri, 1 on no line: check and confirm"
    assert item["since"] == "2026-11-12" and item["count"] == 3


async def test_guard_a_site_role_is_never_asked_and_nothing_to_confirm_is_no_row(monkeypatch):
    from mesiri.domains.costing import router as costing

    async def nothing(**_kw):
        return {"groups": []}

    monkeypatch.setattr(costing, "project_labour", nothing)
    assert await inbox.labour_splits(_Conn(), _auth("SITE_SUPERVISOR"), datetime.date(2026, 11, 15)) == []
    assert await inbox.labour_splits(_Conn(), _auth("OWNER"), datetime.date(2026, 11, 15)) == []
    assert "labour_split" in inbox.KINDS and inbox.MODULE_OF["labour_split"] == "cost"
