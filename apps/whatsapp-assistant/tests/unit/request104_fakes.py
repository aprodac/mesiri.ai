"""Fakes for request 104's cards: an ActionService with no database, the people
a question can go to, and a recording outbound sender."""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from typing import Any

from runtime.agent.actions import ActionService, ActionStore


class MemoryRedis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self.data.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)


class FakeDb:
    """``transaction()`` hands out a connection nothing reads."""

    @contextlib.asynccontextmanager
    async def transaction(self):  # noqa: ANN202
        yield None


class FakeDispatcher:
    def __init__(self, succeed: bool = True) -> None:
        self.dispatched: list[Any] = []
        self.succeed = succeed

    async def dispatch(self, confirmed: Any) -> Any:
        from mesiri_contracts.application.results.execution_result import (
            ExecutionResult,
            ExecutionStatus,
        )

        self.dispatched.append(confirmed)
        ok = self.succeed
        return ExecutionResult(
            status=ExecutionStatus.SUCCEEDED if ok else ExecutionStatus.REJECTED,
            idempotency_key=confirmed.workflow_instance_id,
            material_row_id=str(uuid.uuid4()) if ok else None,
            rejection_reasons=[] if ok else ["no"],
        )


class FakeActions(ActionService):
    """The real service, with the people and the outbound path faked: who a
    question goes to, and what each of them gets (``outcomes`` maps a user id
    to "sent" or a skip reason)."""

    def __init__(
        self,
        people: list[dict[str, Any]] | None = None,
        outcomes: dict[str, str] | None = None,
        dispatcher: Any | None = None,
        redis: MemoryRedis | None = None,
    ) -> None:
        super().__init__(
            store=ActionStore(redis or MemoryRedis()),
            db=FakeDb(),
            actor_reader=SimpleNamespace(),
            dispatcher=dispatcher,
        )
        self.people = people if people is not None else []
        self.outcomes = outcomes or {}
        self.delivered: list[dict[str, Any]] = []
        self.sent_text: list[str] = []

    async def engineers(self, *, organization_id, project_id, site_id, exclude_user):  # noqa: ANN001, ANN201
        return [dict(p) for p in self.people if p["user_id"] != exclude_user]

    async def queue_messages(self, *, organization_id, action_id, payload, text, recipients):  # noqa: ANN001, ANN201
        self.sent_text.append(text)
        queued = [{**p, "notification_id": f"n-{p['user_id']}"} for p in recipients]
        self.delivered.extend(queued)
        return queued

    async def deliver(self, ids, sender):  # noqa: ANN001, ANN201
        return {i: self.outcomes.get(i.removeprefix("n-"), "sent") for i in ids}


ENGINEER = {"user_id": "11111111-1111-4111-8111-aaaaaaaaaaaa", "name": "Ravi", "role": "site engineer"}
MANAGER = {"user_id": "22222222-2222-4222-8222-bbbbbbbbbbbb", "name": "Priya", "role": "project manager"}
