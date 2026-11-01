"""idempotency_uuid: the shared idempotency_keys table is scoped by company.

The integration contract tests (materials, expenses, finance transfers) prove
the end-to-end behaviour against Postgres; these pin the derivation itself.
"""

from __future__ import annotations

import inspect
import uuid

from mesiri.domains.expenses import router as expenses_router
from mesiri.domains.finance import router as finance_router
from mesiri.domains.materials import router as materials_router
from mesiri.domains.shared.idempotency import idempotency_uuid

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


def test_same_company_same_key_is_stable_so_a_retry_still_replays():
    assert idempotency_uuid(ORG_A, "tap-1") == idempotency_uuid(ORG_A, "tap-1")
    # str and UUID organization ids derive the same key.
    assert idempotency_uuid(str(ORG_A), "tap-1") == idempotency_uuid(ORG_A, "tap-1")


def test_two_companies_never_share_a_key():
    assert idempotency_uuid(ORG_A, "tap-1") != idempotency_uuid(ORG_B, "tap-1")


def test_stored_key_is_never_the_raw_client_value():
    key = str(uuid.uuid4())
    assert idempotency_uuid(ORG_A, key) != key


def test_derived_key_cannot_collide_with_a_workflow_instance_id():
    """The WhatsApp path stores uuid4 workflow_instance_ids in the same table;
    a derived key is always a uuid5."""
    assert uuid.UUID(idempotency_uuid(ORG_A, "anything")).version == 5


def test_every_rest_idempotency_key_header_goes_through_the_scoping():
    """Guard for the class: a router that accepts an `Idempotency-Key` header
    must scope it. A new endpoint that forgets fails here."""
    for module in (materials_router, expenses_router, finance_router):
        source = inspect.getsource(module)
        assert 'alias="Idempotency-Key"' in source
        assert "idempotency_uuid(" in source, module.__name__
        assert "idempotency_key=idempotency_key," not in source, module.__name__
        assert "idempotency_key or " not in source, module.__name__
