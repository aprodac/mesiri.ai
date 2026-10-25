"""WEB-17: the dashboard adds site staff by name and WhatsApp number alone,
through the same CreateUserHandler WhatsApp uses (fakes only, no DB)."""

from __future__ import annotations

import uuid

import pytest

from mesiri.application.identity.add_by_number import MemberNotAdded, add_member_by_number
from mesiri.application.identity.fakes import FakeCreateUserExecutionRepository

ORG = "11111111-1111-4111-8111-111111111111"
ADMIN = "22222222-2222-4222-8222-222222222222"


async def _add(repo, **overrides):
    args = dict(
        organization_id=ORG,
        created_by=ADMIN,
        created_by_role="ADMIN",
        full_name="Ravi Menon",
        whatsapp_number="98765 43210",
        role="site_engineer",
        repo=repo,
    )
    args.update(overrides)
    return await add_member_by_number(None, **args)


@pytest.mark.asyncio
async def test_a_number_alone_adds_the_person_with_the_number_whatsapp_sends() -> None:
    repo = FakeCreateUserExecutionRepository()

    user_id = await _add(repo)

    assert isinstance(user_id, uuid.UUID)
    [written] = repo.user_writes
    cmd = written["command"]
    # Stored as WhatsApp sends it: digits, country code first.
    assert cmd.whatsapp_number == "919876543210"
    assert cmd.role == "SITE_ENGINEER"
    assert cmd.full_name == "Ravi Menon"


@pytest.mark.asyncio
async def test_a_number_that_cannot_be_a_phone_is_refused_in_plain_words() -> None:
    repo = FakeCreateUserExecutionRepository()

    with pytest.raises(MemberNotAdded, match="country code"):
        await _add(repo, whatsapp_number="12345")
    assert repo.user_writes == []


@pytest.mark.asyncio
async def test_the_whatsapp_role_rules_apply_a_manager_cannot_make_an_admin() -> None:
    repo = FakeCreateUserExecutionRepository()

    with pytest.raises(MemberNotAdded, match="admin"):
        await _add(repo, created_by_role="PROJECT_MANAGER", role="ADMIN")
    assert repo.user_writes == []


@pytest.mark.asyncio
async def test_a_name_is_required() -> None:
    repo = FakeCreateUserExecutionRepository()

    with pytest.raises(MemberNotAdded, match="name"):
        await _add(repo, full_name="  ")
    assert repo.user_writes == []
