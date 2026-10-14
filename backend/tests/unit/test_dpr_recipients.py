"""BE-15: DPR recipients and WhatsApp opt-ins -- the rules, and the
/dpr/projects/{id}/recipients routes against a fake repository (no Postgres)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.application.dpr import recipients
from mesiri.application.dpr.recipients import (
    RecipientError,
    clean_contact,
    may_message,
    normalize_phone,
)
from mesiri.domains.dpr import router as dpr_router
from mesiri.infrastructure.postgres.repositories import report_recipients as repo_module

# --- rules ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+91 98765 43210", "919876543210"),
        ("98765-43210", "919876543210"),
        ("098765 43210", "919876543210"),
        ("0091 98765 43210", "919876543210"),
        ("+44 7911 123456", "447911123456"),
    ],
)
def test_phone_numbers_become_whatsapp_ids(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "12345", "2345678901", "1" * 16])
def test_numbers_that_cannot_be_a_phone_are_refused(raw):
    with pytest.raises(RecipientError):
        normalize_phone(raw)


def test_contact_fields_are_trimmed():
    assert clean_contact(name="  Mr Shah ", phone="9876543210", label=" Client ") == {
        "name": "Mr Shah",
        "phone": "919876543210",
        "label": "Client",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "", "phone": "9876543210"},
        {"name": "x" * 121, "phone": "9876543210"},
        {"name": "Shah", "phone": "9876543210", "label": "x" * 61},
    ],
)
def test_bad_contacts_are_refused(fields):
    with pytest.raises(RecipientError):
        clean_contact(**fields)


@pytest.mark.parametrize(
    ("consent", "requires_opt_in", "expected"),
    [
        (None, False, (True, None)),  # a company user
        ("opted_in", False, (True, None)),
        ("opted_out", False, (False, "opted_out")),  # STOP wins for users too
        (None, True, (False, "no_opt_in")),  # an outside contact, not yet asked
        ("opted_in", True, (True, None)),
        ("opted_out", True, (False, "opted_out")),
    ],
)
def test_who_may_be_messaged(consent, requires_opt_in, expected):
    assert may_message(consent_state=consent, requires_opt_in=requires_opt_in) == expected


# --- routes -----------------------------------------------------------------

ORG = uuid.uuid4()
PROJECT = uuid.uuid4()
ACTOR = uuid.uuid4()


class _FakeRepo:
    """In-memory stand-in for PostgresReportRecipientRepository."""

    rows: list[dict] = []
    consents: list[dict] = []
    users: set = set()
    projects: set = set()

    def __init__(self, conn):
        pass

    async def project_exists(self, *, organization_id, project_id):
        return project_id in type(self).projects

    async def active_user_in_org(self, *, organization_id, user_id):
        return user_id in type(self).users

    async def has_active(self, *, project_id, user_id=None, phone=None):
        return any(
            r["removed"] is False and ((user_id and r["user_id"] == user_id) or (phone and r["phone"] == phone))
            for r in type(self).rows
        )

    async def add(self, *, organization_id, project_id, actor_user_id, user_id=None, name=None, phone=None, label=None):
        rid = uuid.uuid4()
        type(self).rows.append(
            {"id": rid, "user_id": user_id, "name": name or "A User", "phone": phone or ("91" + "9" * 10 if user_id else None),
             "label": label, "removed": False}
        )
        return rid

    async def remove(self, *, organization_id, project_id, recipient_id, actor_user_id):
        for r in type(self).rows:
            if r["id"] == recipient_id and not r["removed"]:
                r["removed"] = True
                return True
        return False

    async def record_consent(self, *, organization_id, phone, state, method, note=None, actor_user_id=None):
        type(self).consents.append({"phone": phone, "state": state, "method": method, "note": note})

    def _with_consent(self, r):
        state = next((c["state"] for c in reversed(type(self).consents) if c["phone"] == r["phone"]), None)
        return {**r, "project_id": PROJECT, "user_role": "ADMIN" if r["user_id"] else None, "consent_state": state}

    async def list_active(self, *, organization_id, project_id):
        return [self._with_consent(r) for r in type(self).rows if not r["removed"]]

    async def find_active(self, *, organization_id, project_id, recipient_id):
        return next((r for r in await self.list_active(organization_id=organization_id, project_id=project_id)
                     if r["id"] == recipient_id), None)


@pytest.fixture
def repo(monkeypatch):
    _FakeRepo.rows, _FakeRepo.consents, _FakeRepo.users, _FakeRepo.projects = [], [], set(), {PROJECT}
    monkeypatch.setattr(repo_module, "PostgresReportRecipientRepository", _FakeRepo)
    return _FakeRepo


def _auth(role="ADMIN"):
    return SimpleNamespace(
        user_id=ACTOR,
        organization_id=ORG,
        role=role,
        project_scope=SimpleNamespace(grants_all_org_projects=True, project_ids=set()),
    )


async def _add(role="ADMIN", **body):
    return await dpr_router.add_report_recipient(
        PROJECT, dpr_router.AddRecipientRequest(**body), auth_context=_auth(role), conn=None
    )


async def test_an_empty_list_means_the_defaults(repo):
    listed = await dpr_router.list_report_recipients(PROJECT, auth_context=_auth("SITE_ENGINEER"), conn=None)
    assert listed["using_defaults"] is True
    assert listed["recipients"] == []


async def test_a_contact_added_without_opt_in_will_not_receive_yet(repo):
    added = await _add(name="Mr Shah", phone="+91 98765 43210", label="Client")
    assert added["kind"] == "contact"
    assert added["phone"] == "919876543210"
    assert added["opt_in"] is None
    assert added["will_receive"] is False

    listed = await dpr_router.list_report_recipients(PROJECT, auth_context=_auth(), conn=None)
    assert listed["using_defaults"] is False


async def test_a_contact_added_with_opt_in_records_it_in_the_same_step(repo):
    added = await _add(name="Mr Shah", phone="9876543210", opted_in=True, opt_in_note="Signed contract clause 12")
    assert added["opt_in"] == "opted_in"
    assert added["will_receive"] is True
    assert repo.consents == [
        {"phone": "919876543210", "state": "opted_in", "method": "recorded_by_admin", "note": "Signed contract clause 12"}
    ]


async def test_a_company_user_receives_without_an_opt_in(repo):
    user_id = uuid.uuid4()
    repo.users.add(user_id)
    added = await _add(user_id=str(user_id))
    assert added["kind"] == "user"
    assert added["will_receive"] is True


async def test_opt_out_then_opt_in_follows_the_latest(repo):
    added = await _add(name="Mr Shah", phone="9876543210", opted_in=True)
    rid = uuid.UUID(added["id"])
    out = await dpr_router.record_recipient_opt_out(
        PROJECT, rid, dpr_router.ConsentRequest(note="Asked by phone"), auth_context=_auth(), conn=None
    )
    assert out["opt_in"] == "opted_out" and out["will_receive"] is False
    back = await dpr_router.record_recipient_opt_in(
        PROJECT, rid, dpr_router.ConsentRequest(), auth_context=_auth(), conn=None
    )
    assert back["opt_in"] == "opted_in" and back["will_receive"] is True


async def test_removing_the_last_recipient_brings_the_defaults_back(repo):
    added = await _add(name="Mr Shah", phone="9876543210")
    await dpr_router.remove_report_recipient(PROJECT, uuid.UUID(added["id"]), auth_context=_auth(), conn=None)
    listed = await dpr_router.list_report_recipients(PROJECT, auth_context=_auth(), conn=None)
    assert listed["using_defaults"] is True


@pytest.mark.parametrize(
    ("role", "body", "status"),
    [
        ("SITE_ENGINEER", {"name": "Shah", "phone": "9876543210"}, 403),
        ("ADMIN", {"name": "Shah", "phone": "123"}, 422),
        ("ADMIN", {"name": "", "phone": "9876543210"}, 422),
        ("ADMIN", {"user_id": str(uuid.uuid4())}, 422),  # not in this company
        ("ADMIN", {"user_id": str(uuid.uuid4()), "phone": "9876543210"}, 422),
    ],
)
async def test_refused_requests(repo, role, body, status):
    with pytest.raises(HTTPException) as exc:
        await _add(role, **body)
    assert exc.value.status_code == status


async def test_the_same_contact_twice_is_a_conflict(repo):
    await _add(name="Mr Shah", phone="9876543210")
    with pytest.raises(HTTPException) as exc:
        await _add(name="Shah again", phone="+91 98765 43210")
    assert exc.value.status_code == 409


async def test_another_companys_project_is_not_found(repo):
    repo.projects = set()
    with pytest.raises(HTTPException) as exc:
        await dpr_router.list_report_recipients(PROJECT, auth_context=_auth(), conn=None)
    assert exc.value.status_code == 404


async def test_removing_an_unknown_recipient_is_not_found(repo):
    with pytest.raises(HTTPException) as exc:
        await dpr_router.remove_report_recipient(PROJECT, uuid.uuid4(), auth_context=_auth(), conn=None)
    assert exc.value.status_code == 404


def test_manager_roles_are_admins_and_project_managers():
    assert recipients.MANAGER_ROLES == {"ADMIN", "PROJECT_MANAGER"}
