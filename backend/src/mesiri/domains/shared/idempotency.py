"""Scope a client-supplied `Idempotency-Key` to the calling company.

`idempotency_keys` is one table shared by every organization, keyed by the
raw `key` string. The REST endpoints that accept an `Idempotency-Key` header
used to store and look up the client's value as-is, so company B sending a key
company A had already used was handed A's stored result (A's row ids and
quantities) and B's own write was silently skipped.

Every REST endpoint now passes the client's header through
`idempotency_uuid` before it touches the table. The derivation is
deterministic, so a retry from the same company is the same key and still
replays; two companies never share one.

Only REST client keys go through this. The WhatsApp/workflow path keeps using
its server-minted `workflow_instance_id` (a random uuid4) as the key, because
the executors also use that value to advance `workflow_instances`. A derived
key is a uuid5, so it can never collide with one of those.
"""

from __future__ import annotations

import uuid

# Fixed forever: changing it re-keys every stored REST idempotency row.
_IDEMPOTENCY_NAMESPACE = uuid.UUID("6f1d3c2a-9b4e-5c7a-8d10-2e3f4a5b6c7d")


def idempotency_uuid(organization_id: uuid.UUID | str, client_key: str) -> str:
    """The `idempotency_keys.key` for `client_key` sent by `organization_id`."""
    return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, f"{organization_id}:{client_key}"))
