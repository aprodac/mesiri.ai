"""SS-66: a person's private learning company (Learn Mesiri's sample Green Villa).

Design: docs/plans/guided-demo-plan.md section 17. In short:

- one per person (``organizations.sandbox_user_id``), status ``sandbox`` (``lifecycle.SANDBOX``), so nothing that runs
  on its own (reports, reminders, tips, WhatsApp) ever reaches it;
- no phone numbers anywhere in it: the outbound sender is keyed by phone, so nothing can be sent;
- made with the one company-creation step (``create_company``), then filled with two weeks of history by the shared
  story (``sample_story.seed``) through the real API, as its owner, so every record passes the usual checks;
- opened with a sandbox token: an ordinary access token for a sandbox user, plus a ``sandbox`` claim naming the real
  company; it reaches only the sandbox (the user belongs to it);
- removed with the one company-delete step (``delete_company``): on Reset, after 30 days unopened, or once the real
  company or person is gone.

Nothing here commits for the caller: each step opens its own transaction on the engine it is given, so the seed (which
goes through the API, in other transactions) sees the company once it exists.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.application.organizations.sample_story import DEMO_PROJECT, DEMO_SITES, seed
from mesiri.domains.organizations import lifecycle
from mesiri.domains.organizations import settings as org_settings

_log = logging.getLogger(__name__)

#: The sample company's name, as the banner and the switcher show it.
SANDBOX_NAME = "Sample: Green Villa Builders"
#: Removed when not opened for this long (D-PG1: kept until reset; this only clears abandoned ones).
KEEP_UNOPENED = dt.timedelta(days=30)
#: How long one sandbox token lasts: a learning session.
TOKEN_LIFETIME = dt.timedelta(hours=8)
#: Expired or orphaned sandboxes removed per open, so a backlog never slows one person down.
CLEANUP_PER_OPEN = 3
#: Emails of sandbox people: a reserved domain (RFC 2606), so they can never be a real inbox or log in.
EMAIL_DOMAIN = "sandbox.mesiri.invalid"

#: The roles a person can play in their sandbox (D-PG4), and who plays them. The owner is the person themself.
OWNER = "ADMIN"
ROLES: dict[str, str] = {
    "PROJECT_MANAGER": "Anil (project manager)",
    "SITE_ENGINEER": "Ravi (site engineer)",
    "FINANCE": "Meera (accounts)",
}
PLAYABLE_ROLES: tuple[str, ...] = (OWNER, *ROLES)


class SandboxError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RealPerson:
    """Who the sandbox is for: a signed-in person in a real company."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    full_name: str


@dataclass
class Opened:
    token: str
    expires_at: dt.datetime
    organization_id: uuid.UUID
    name: str
    role: str
    user_name: str
    created: bool
    #: The sample company's own date (SS-74a): the day its planned simulation is at.
    today: dt.date | None = None
    seeded: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)


_SANDBOX_OF = sa.text(
    "SELECT id, name, created_at, sandbox_expires_at, sandbox_today FROM organizations WHERE sandbox_user_id = :u"
)


def day_zero(today: dt.date) -> dt.date:
    """The date a new sample company starts on (SS-74a): the latest Saturday, so its seeded weeks end on a pay day
    and its planned simulation's day 0 is a Saturday (application/learn/sample_plan.py ``weekday``)."""
    return today - dt.timedelta(days=(today.weekday() - 5) % 7)


def _email(org_id: uuid.UUID, role: str) -> str:
    return f"{role.lower()}.{org_id.hex}@{EMAIL_DOMAIN}"


async def real_person(conn: Any, user_id: uuid.UUID, organization_id: uuid.UUID) -> RealPerson:
    """The signed-in person, checked again here: an active person of a real (not sandbox) company."""
    row = (await conn.execute(sa.text(
        "SELECT u.id, u.full_name, u.status, u.organization_id, o.sandbox_of FROM users u "
        "JOIN organizations o ON o.id = u.organization_id WHERE u.id = :u"), {"u": user_id})).mappings().first()
    if row is None or row["organization_id"] != organization_id or str(row["status"] or "").lower() != "active":
        raise SandboxError("Sign in again to open the sample company.", 401)
    if row["sandbox_of"] is not None:
        raise SandboxError("You are already in the sample company.", 403)
    return RealPerson(user_id=row["id"], organization_id=organization_id, full_name=row["full_name"] or "Owner")


async def find(conn: Any, person: RealPerson) -> dict[str, Any] | None:
    row = (await conn.execute(_SANDBOX_OF, {"u": person.user_id})).mappings().first()
    return dict(row) if row else None


async def _make(engine: Any, person: RealPerson, now: dt.datetime) -> dict[str, Any]:
    """The company, its people and settings, in one transaction. Returns what the seed needs."""
    async with engine.begin() as conn:
        org_id_hint = uuid.uuid4()
        created = await create_company(conn, NewCompany(
            name=SANDBOX_NAME, owner_name=person.full_name, owner_email=_email(org_id_hint, OWNER),
            project_name=DEMO_PROJECT, site_names=DEMO_SITES, signup_source="sandbox",
        ), now=now)
        org_id = created.organization_id
        await conn.execute(sa.text(
            "UPDATE organizations SET status = :s, sandbox_of = :real, sandbox_user_id = :u, sandbox_expires_at = :e, "
            "sandbox_today = :d, sandbox_day0 = :d, trial_started_at = NULL, trial_ends_at = NULL WHERE id = :o"),
            {"s": lifecycle.SANDBOX, "real": person.organization_id, "u": person.user_id, "e": now + KEEP_UNOPENED,
             "d": day_zero(now.date()), "o": org_id})
        others = []
        for role, name in ROLES.items():
            uid = uuid.uuid4()
            await conn.execute(sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, created_at, "
                "updated_at) VALUES (:id, :o, :e, :h, :n, :r, 'active', :t, :t)"),
                {"id": uid, "o": org_id, "e": _email(org_id, role), "h": _unusable_password(), "n": name,
                 "r": role, "t": now})
            others.append({"id": uid, "role": role})
        for key, value in ((org_settings.ASSISTANT_MODE, org_settings.ASSISTANT_MODE_API),
                           (org_settings.ENABLED_MODULES, list(org_settings.MODULES))):
            await conn.execute(sa.text(
                "INSERT INTO organization_settings (id, organization_id, key, value) "
                "VALUES (gen_random_uuid(), :o, :k, CAST(:v AS jsonb)) "
                "ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value"),
                {"o": org_id, "k": key, "v": _json(value)})
    return {"organization_id": org_id, "name": SANDBOX_NAME, "owner_id": created.owner_user_id,
            "today": day_zero(now.date()),
            "owner_name": person.full_name, "project_id": created.project_id,
            "site_ids": [s.site_id for s in created.sites], "others": others}


def _unusable_password() -> str:
    """A real hash of a secret nobody keeps: the login check runs as for anyone and always says no."""
    import bcrypt

    return bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt()).decode()


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


def sandbox_token(*, user_id: uuid.UUID, org_id: uuid.UUID, role: str, name: str, real_org: uuid.UUID,
                  now: dt.datetime, today: dt.date) -> tuple[str, dt.datetime]:
    """An access token for a sandbox user; the ``sandbox`` claim marks it (the dashboard shows the banner, and
    ``/learn/sandbox`` refuses it), and ``today`` is the sample company's own date (SS-74a, domains/shared/clock.py).
    When that date moves, the route that moves it gives a new token."""
    import jwt

    from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

    expires = now + TOKEN_LIFETIME
    payload = {"sub": str(user_id), "org": str(org_id), "role": role, "name": name, "org_name": SANDBOX_NAME,
               "sandbox": str(real_org), "today": today.isoformat(), "exp": expires}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM), expires


class _InProcessApi:
    """``sample_story.seed``'s client: the app's own routes, called in-process as the sandbox owner."""

    def __init__(self, app: Any, token: str) -> None:
        import httpx

        self._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sandbox.internal",
                                         headers={"Authorization": f"Bearer {token}"}, timeout=60.0)

    async def call(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                   idempotency_key: str | None = None) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = await self._client.request(method, path, json=json, params=params, headers=headers)
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        return _Response(ok=200 <= response.status_code < 300, status=response.status_code, body=body)

    async def close(self) -> None:
        await self._client.aclose()


@dataclass
class _Response:
    ok: bool
    status: int
    body: Any


async def _seed(app: Any, info: dict[str, Any], real_org: uuid.UUID, today: dt.date) -> tuple[dict[str, int], list[str]]:
    token, _ = sandbox_token(user_id=info["owner_id"], org_id=info["organization_id"], role=OWNER,
                             name=info["owner_name"], real_org=real_org, now=dt.datetime.now(dt.UTC),
                             today=info["today"])
    client = _InProcessApi(app, token)
    try:
        return await seed(client, info, today=today)
    finally:
        await client.close()


async def _seed_in_fresh_context(app: Any, info: dict[str, Any], real_org: uuid.UUID, today: dt.date):
    """Run the seed with no request state carried in: no bound company, no shared request transaction. Each
    in-process call then opens its own, scoped to the sandbox by its own token, as a browser request would."""
    return await asyncio.create_task(_seed(app, info, real_org, today), context=contextvars.Context())


async def open_sandbox(engine: Any, app: Any, person: RealPerson, *, role: str = OWNER,
                       now: dt.datetime | None = None) -> Opened:
    """Mine, made first if there is none; its expiry moved on; a token for the role asked."""
    now = now or dt.datetime.now(dt.UTC)
    role = (role or OWNER).upper()
    if role not in PLAYABLE_ROLES:
        raise SandboxError(f"role must be one of {list(PLAYABLE_ROLES)}", 422)
    await cleanup(engine, now=now)
    async with engine.connect() as conn:
        existing = await find(conn, person)
    created, seeded, failed = False, {}, []
    if existing is None:
        try:
            info = await _make(engine, person, now)
        except sa.exc.IntegrityError as exc:  # two opens at once: the other one made it
            async with engine.connect() as conn:
                if await find(conn, person) is None:
                    raise SandboxError("Could not make the sample company; try again.", 409) from exc
        else:
            created = True
            seeded, failed = await _seed_in_fresh_context(app, info, person.organization_id, info["today"])
            if failed:
                _log.warning("learn_sandbox.seed_failed org=%s failed=%s", info["organization_id"], failed[:10])
            # The player builds on this module, so it is imported here.
            from mesiri.application.learn.sandbox_player import save_day_zero

            await save_day_zero(engine, info["organization_id"])  # Go back to day 0 = a fresh start (SS-74d)
    async with engine.begin() as conn:
        row = await find(conn, person)
        if row is None:
            raise SandboxError("The sample company was removed; open it again.", 409)
        # A sample company made before it had its own date (SS-74a) carries on from the day its records run to.
        await conn.execute(sa.text("UPDATE organizations SET sandbox_expires_at = :e, "
                                   "sandbox_today = COALESCE(sandbox_today, CAST(created_at AS date)) WHERE id = :o"),
                           {"e": now + KEEP_UNOPENED, "o": row["id"]})
        today = (await conn.execute(sa.text("SELECT sandbox_today FROM organizations WHERE id = :o"),
                                    {"o": row["id"]})).scalar_one()
        # Everyone in the sample company is explained to the way this person chose (UX-22 start mode), and nobody
        # there asks "How would you like to start?" again: it is the same person playing each role. Copied on every
        # open, so a change made in their own company follows them in.
        await conn.execute(sa.text(
            "UPDATE users SET start_mode = COALESCE((SELECT start_mode FROM users WHERE id = :me), 'guided') "
            "WHERE organization_id = :o"), {"me": person.user_id, "o": row["id"]})
        user = (await conn.execute(sa.text(
            "SELECT id, full_name FROM users WHERE organization_id = :o AND upper(role) = :r "
            "ORDER BY created_at LIMIT 1"), {"o": row["id"], "r": role})).mappings().first()
    if user is None:
        raise SandboxError("That role is not in your sample company; reset it to get every role.", 409)
    token, expires = sandbox_token(user_id=user["id"], org_id=row["id"], role=role, name=user["full_name"],
                                   real_org=person.organization_id, now=now, today=today)
    return Opened(token=token, expires_at=expires, organization_id=row["id"], name=row["name"], role=role,
                  user_name=user["full_name"], created=created, today=today, seeded=seeded, failed=failed)


async def remove_sandbox(engine: Any, person: RealPerson) -> bool:
    """Mine, gone now (Reset or Leave for good). False when there was none."""
    async with engine.begin() as conn:
        row = await find(conn, person)
        if row is None:
            return False
        await _delete(conn, row["id"])
    return True


async def _delete(conn: Any, org_id: uuid.UUID) -> None:
    # Only ever a sandbox: the one guard that keeps this from removing a real company.
    status = (await conn.execute(sa.text("SELECT sandbox_of FROM organizations WHERE id = :o"), {"o": org_id})).scalar()
    if status is None:
        raise SandboxError("Not a sample company.", 409)
    await delete_company(conn, org_id)


_STALE = sa.text(
    "SELECT o.id FROM organizations o WHERE o.sandbox_of IS NOT NULL AND ("
    " o.sandbox_expires_at < :now"
    " OR NOT EXISTS (SELECT 1 FROM organizations r WHERE r.id = o.sandbox_of)"
    " OR NOT EXISTS (SELECT 1 FROM users p WHERE p.id = o.sandbox_user_id AND p.organization_id = o.sandbox_of)"
    ") ORDER BY o.sandbox_expires_at NULLS FIRST LIMIT :n"
)


async def cleanup(engine: Any, *, now: dt.datetime, limit: int = CLEANUP_PER_OPEN) -> int:
    """Remove a few sandboxes nobody opened for 30 days, or whose real company or person is gone. Never raises: a
    sandbox that can't be removed now is tried again next time."""
    removed = 0
    try:
        async with engine.connect() as conn:
            stale = [r[0] for r in (await conn.execute(_STALE, {"now": now, "n": limit})).all()]
    except Exception:  # noqa: BLE001
        _log.exception("learn_sandbox.cleanup_list_failed")
        return 0
    for org_id in stale:
        try:
            async with engine.begin() as conn:
                await _delete(conn, org_id)
            removed += 1
        except Exception:  # noqa: BLE001
            _log.exception("learn_sandbox.cleanup_failed org=%s", org_id)
    return removed
