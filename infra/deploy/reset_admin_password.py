#!/usr/bin/env python3
"""Reset a control-panel (platform admin) password from the server (INF-16).

The control panel has no "forgot password", and on 26 Oct 2026 nobody
remembered theirs, so no admin could log in to add one. Run on the VPS by
.github/workflows/claude-ops.yml (task vps-admin-password), with the app's
venv and PYTHONPATH:

    printf '%s' "$NEW_PASSWORD" | python reset_admin_password.py <email> <who>
    python reset_admin_password.py --list

The new password comes on stdin only, never a command line or a log. Uses the
panel's own pieces: the database login and users table of
admin/platform_users_router.py, the login's hash_password/verify_password, and
record_admin_action, so the reset is in the admin audit log in the same
transaction. Emails are printed masked.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

ENV_FILE = os.environ.get("ENV_FILE", "/opt/mesiri/.env")
MIN_LENGTH = 8  # the panel's own rule (PlatformUserCreate)


def load_db_env(path: str) -> None:
    """The MESIRI_POSTGRES__* lines of the app's .env, as systemd reads them."""
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            if key.startswith("MESIRI_POSTGRES__"):
                os.environ[key] = value.strip().strip("'\"")


def masked(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}" if domain else "***"


async def list_admins() -> None:
    import sqlalchemy as sa

    from admin.platform_users_router import get_engine, users_table

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.select(users_table.c.email, users_table.c.status)
                    .where(users_table.c.role == "ADMIN", users_table.c.organization_id.is_(None))
                    .order_by(users_table.c.created_at)
                )
            ).all()
    finally:
        await engine.dispose()
    print(f"{len(rows)} control-panel admin(s):")
    for row in rows:
        print(f"  {masked(row.email or '')}  ({row.status})")


async def reset(email: str, who: str, password: str) -> None:
    import sqlalchemy as sa

    from admin.platform_users_router import get_engine, users_table
    from mesiri.application.audit.record import record_admin_action
    from mesiri.domains.audit.actions import ACTOR_SYSTEM, PLATFORM_ADMIN_UPDATED, AuditActor
    from mesiri.domains.identity.auth_service import hash_password, verify_password

    shown = masked(email)
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    sa.select(users_table.c.id, users_table.c.status).where(
                        sa.func.lower(users_table.c.email) == email.lower(),
                        users_table.c.role == "ADMIN",
                        users_table.c.organization_id.is_(None),
                    )
                )
            ).all()
            if len(rows) != 1:
                sys.exit(
                    f"No single control-panel admin with the email {shown} (found {len(rows)}). "
                    "Nothing changed. Run with an empty email to list them."
                )
            user_id, status = rows[0]
            await conn.execute(
                users_table.update()
                .where(users_table.c.id == user_id)
                .values(hashed_password=hash_password(password))
            )
            await record_admin_action(
                conn,
                actor=AuditActor(kind=ACTOR_SYSTEM, label=f"Server password reset ({who})"),
                action=PLATFORM_ADMIN_UPDATED,
                target_type="user",
                target_id=user_id,
                summary=f"Password reset from the server for {shown}",
                details={"password": "reset"},
            )
            stored = (
                await conn.execute(
                    sa.select(users_table.c.hashed_password).where(users_table.c.id == user_id)
                )
            ).scalar_one()
            if not verify_password(password, stored):
                # Raising inside begin() rolls the change and its audit entry back.
                raise RuntimeError("the new password did not verify; nothing changed")
    finally:
        await engine.dispose()
    print(f"Password reset for {shown}; it verifies against the login check.")
    if status != "active":
        print(f"Note: this account's status is '{status}', so the login may still refuse it.")


def main() -> None:
    # passlib's harmless "module 'bcrypt' has no attribute '__about__'" trace.
    logging.getLogger("passlib").setLevel(logging.ERROR)
    args = sys.argv[1:]
    load_db_env(ENV_FILE)
    if args in ([], ["--list"]):
        asyncio.run(list_admins())
        return
    if len(args) != 2:
        sys.exit("usage: reset_admin_password.py <email> <who>  (password on stdin) | --list")
    email, who = args[0].strip(), re.sub(r"[^A-Za-z0-9_.@ -]", "", args[1])[:40] or "unknown"
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
        sys.exit("That is not an email address. Nothing changed.")
    password = sys.stdin.read().rstrip("\r\n")
    if len(password) < MIN_LENGTH or "\n" in password:
        sys.exit(f"The new password must be one line of at least {MIN_LENGTH} characters. Nothing changed.")
    asyncio.run(reset(email, who, password))


if __name__ == "__main__":
    main()
