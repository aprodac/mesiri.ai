"""SS-06 / WEB-12: web signup and login by a WhatsApp code, through /auth.

The database is faked (codes in memory, users from a list); the code rules
themselves are covered in backend/tests/unit/test_login_codes.py and the
store in backend/tests/integration/test_login_codes_postgres.py."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import code_login, code_senders
from auth.router import router as auth_router
from mesiri.application.identity.login_codes import MAX_ATTEMPTS, StoredCode
from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    CreatedCompany,
    validate,
)
from mesiri.application.organizations.signup_guard import SignupRefused
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

_PHONE = "919876543210"


class _Store:
    rows: list[dict] = []

    def __init__(self, conn) -> None:
        pass

    async def sent_since(self, phone, purpose, since):
        return [r["created_at"] for r in self._for(phone, purpose) if r["created_at"] >= since]

    def _for(self, phone, purpose):
        return [r for r in _Store.rows if r["phone"] == phone and r["purpose"] == purpose]

    async def add(self, **row):
        _Store.rows.append({**row, "id": uuid.uuid4(), "attempts": 0, "consumed_at": None})

    async def void_open(self, phone, purpose, now):
        for r in self._for(phone, purpose):
            r["consumed_at"] = r["consumed_at"] or now

    async def latest_open(self, phone, purpose, now):
        rows = [
            r
            for r in self._for(phone, purpose)
            if r["consumed_at"] is None and r["expires_at"] > now and r["attempts"] < MAX_ATTEMPTS
        ]
        if not rows:
            return None
        r = rows[-1]
        return StoredCode(id=r["id"], code_hash=r["code_hash"], attempts=r["attempts"])

    async def count_attempt(self, code_id):
        next(r for r in _Store.rows if r["id"] == code_id)["attempts"] += 1

    async def consume(self, code_id, now):
        next(r for r in _Store.rows if r["id"] == code_id)["consumed_at"] = now


class _Begin:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return None


class _Engine:
    def begin(self):
        return _Begin()


@pytest.fixture
def env(monkeypatch):
    _Store.rows = []
    state = SimpleNamespace(
        users=[],
        signup_open=True,
        created=[],
        create_error=None,
    )

    async def fake_users(conn, phone, *, active_only):
        return [u for u in state.users if u.phone == phone and (u.active or not active_only)]

    async def fake_check_signup(conn, attempt):
        if not state.signup_open:
            raise SignupRefused("Sign-up is closed for now.")

    async def fake_create(conn, new):
        if state.create_error:
            raise state.create_error
        new = validate(new)
        state.created.append(new)
        return CreatedCompany(
            organization_id=uuid.uuid4(),
            name=new.name,
            deployment_type="SaaS",
            db_route="shared-cluster-01",
            status=new.start_as,
            signup_source=new.signup_source,
            timezone=new.timezone,
            created_at=dt.datetime.now(dt.UTC),
            trial_started_at=None,
            trial_ends_at=None,
            owner_user_id=uuid.uuid4(),
            owner_email=None,
            owner_whatsapp_number=new.owner_phone,
            project_id=uuid.uuid4(),
            site_id=uuid.uuid4(),
        )

    monkeypatch.setenv(code_senders.SENDER_SETTING, "dev")
    monkeypatch.setattr(code_login, "_engine", lambda: _Engine())
    monkeypatch.setattr(code_login, "PostgresLoginCodeStore", _Store)
    monkeypatch.setattr(code_login, "_users_with_phone", fake_users)
    monkeypatch.setattr(code_login, "check_signup", fake_check_signup)
    monkeypatch.setattr(code_login, "create_company", fake_create)

    app = FastAPI()
    app.include_router(auth_router)
    state.client = TestClient(app)
    return state


def _user(**overrides):
    fields = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "full_name": "Suresh",
        "role": "PROJECT_MANAGER",
        "org_name": "Suresh Builders",
        "phone": _PHONE,
        "active": True,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _claims(response) -> dict:
    assert response.status_code == 200, response.text
    return jwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])


# --- login by code (WEB-12) -----------------------------------------------------


def test_any_active_user_logs_in_with_the_code(env) -> None:
    user = _user()
    env.users.append(user)
    sent = env.client.post("/auth/code/request", json={"phone": "+91 98765 43210"})
    assert sent.status_code == 202
    body = sent.json()
    assert body["resend_after_s"] == 60 and body["expires_in_s"] == 600

    claims = _claims(
        env.client.post("/auth/code/login", json={"phone": "9876543210", "code": body["dev_code"]})
    )
    assert claims["sub"] == str(user.id)
    assert claims["org"] == str(user.organization_id)
    assert claims["role"] == "PROJECT_MANAGER"
    assert claims["org_name"] == "Suresh Builders"


def test_unknown_number_gets_the_same_answer_but_no_code(env) -> None:
    sent = env.client.post("/auth/code/request", json={"phone": _PHONE})
    assert sent.status_code == 202
    assert sent.json()["dev_code"] is None
    assert len(_Store.rows) == 1  # counted toward the limits all the same


def test_wrong_code_then_expired_code(env) -> None:
    env.users.append(_user())
    code = env.client.post("/auth/code/request", json={"phone": _PHONE}).json()["dev_code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_ATTEMPTS):
        refused = env.client.post("/auth/code/login", json={"phone": _PHONE, "code": wrong})
        assert refused.status_code == 401
        assert "isn't right" in refused.json()["detail"]
    dead = env.client.post("/auth/code/login", json={"phone": _PHONE, "code": code})
    assert dead.status_code == 401
    assert "expired" in dead.json()["detail"]


def test_asking_again_at_once_is_429_with_retry_after(env) -> None:
    env.users.append(_user())
    env.client.post("/auth/code/request", json={"phone": _PHONE})
    again = env.client.post("/auth/code/request", json={"phone": _PHONE})
    assert again.status_code == 429
    assert int(again.headers["retry-after"]) > 0


def test_number_on_two_accounts_is_refused_not_guessed(env) -> None:
    env.users.extend([_user(), _user()])
    code = env.client.post("/auth/code/request", json={"phone": _PHONE}).json()["dev_code"]
    clash = env.client.post("/auth/code/login", json={"phone": _PHONE, "code": code})
    assert clash.status_code == 409


def test_bad_phone_is_400(env) -> None:
    assert env.client.post("/auth/code/request", json={"phone": "12"}).status_code == 400


def test_unavailable_until_the_template_is_approved(env, monkeypatch) -> None:
    monkeypatch.setenv(code_senders.SENDER_SETTING, "whatsapp")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "v")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "s")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "t")
    monkeypatch.setenv("WHATSAPP_APPROVED_TEMPLATES", "mesiri_dpr_delivery")
    refused = env.client.post("/auth/code/request", json={"phone": _PHONE})
    assert refused.status_code == 503

    monkeypatch.setenv("WHATSAPP_APPROVED_TEMPLATES", "mesiri_dpr_delivery,mesiri_login_code")
    sender = code_senders.build_login_code_sender()
    assert isinstance(sender, code_senders.WhatsAppLoginCodeSender)
    assert sender.echoes_code is False


# --- web signup (SS-06) ---------------------------------------------------------


def _signup_ticket(env, phone=_PHONE) -> str:
    code = env.client.post("/auth/code/request", json={"phone": phone, "purpose": "signup"}).json()[
        "dev_code"
    ]
    verified = env.client.post("/auth/code/verify", json={"phone": phone, "code": code})
    assert verified.status_code == 200, verified.text
    return verified.json()["signup_token"]


def test_signup_creates_a_web_trial_and_logs_the_owner_in(env) -> None:
    ticket = _signup_ticket(env)
    response = env.client.post(
        "/auth/signup",
        json={
            "signup_token": ticket,
            "owner_name": " Suresh  Kumar ",
            "company_name": "Suresh Builders",
            "site_name": "Green Villa, Kakkanad",
        },
    )
    claims = _claims(response)
    new = env.created[0]
    assert (new.signup_source, new.start_as, new.auto_dpr) == ("web", "trial", True)
    assert new.owner_phone == _PHONE
    assert new.project_name == new.site_name == "Green Villa, Kakkanad"
    assert claims["role"] == "ADMIN"
    assert claims["name"] == "Suresh Kumar"
    assert claims["org_name"] == "Suresh Builders"
    assert len(env.created) == 1


def test_signup_closed_is_403_before_any_code(env) -> None:
    env.signup_open = False
    closed = env.client.post("/auth/code/request", json={"phone": _PHONE, "purpose": "signup"})
    assert closed.status_code == 403
    assert _Store.rows == []


def test_registered_number_is_told_to_log_in(env) -> None:
    env.users.append(_user(active=False))
    taken = env.client.post("/auth/code/request", json={"phone": _PHONE, "purpose": "signup"})
    assert taken.status_code == 409
    assert "Log in" in taken.json()["detail"]


def test_a_login_code_does_not_verify_a_signup(env) -> None:
    env.users.append(_user())
    code = env.client.post("/auth/code/request", json={"phone": _PHONE}).json()["dev_code"]
    assert (
        env.client.post("/auth/code/verify", json={"phone": _PHONE, "code": code}).status_code
        == 401
    )


def test_signup_needs_a_real_ticket(env) -> None:
    forged = jwt.encode({"typ": "signup_ticket", "phone": _PHONE}, "guess", algorithm=ALGORITHM)
    response = env.client.post(
        "/auth/signup",
        json={"signup_token": forged, "owner_name": "A", "company_name": "B", "site_name": "C"},
    )
    assert response.status_code == 401
    assert env.created == []


def test_signup_switched_off_after_the_code_is_refused(env) -> None:
    ticket = _signup_ticket(env)
    env.signup_open = False
    response = env.client.post(
        "/auth/signup",
        json={"signup_token": ticket, "owner_name": "A", "company_name": "B", "site_name": "C"},
    )
    assert response.status_code == 403
    assert env.created == []


def test_create_company_refusals_keep_their_status(env) -> None:
    ticket = _signup_ticket(env)
    env.create_error = CompanyCreationError(
        "That WhatsApp number already belongs to another user", conflict=True
    )
    body = {"signup_token": ticket, "owner_name": "A", "company_name": "B", "site_name": "C"}
    assert env.client.post("/auth/signup", json=body).status_code == 409
    env.create_error = CompanyCreationError("Company name is required")
    assert env.client.post("/auth/signup", json=body).status_code == 400
