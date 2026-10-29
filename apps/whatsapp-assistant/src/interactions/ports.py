"""Ports the Interaction layer depends on.

Concrete implementations live in the backend Application layer (M8) and are
wired in runtime/dependencies.py — the only file that knows about both
interactions/ and backend.application. interactions/ defines this port
itself (mirrors how workflows/ports.py defines what *it* depends on).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from mesiri_contracts.application.results.execution_result import ExecutionResult
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

if TYPE_CHECKING:
    from backend.ports import ActorIdentity


class ExecutionDispatcher(Protocol):
    """Executes a confirmed action's domain write. Must never raise — any
    unhandled exception must be caught by the implementation and reported as
    ExecutionResult(FAILED, ...) instead (see the M8 plan's rejection-vs-
    failure semantics: FAILED leaves the workflow at CONFIRMED, recoverable)."""

    async def dispatch(self, confirmed: ConfirmedActionV2) -> ExecutionResult: ...


class ReceiptBuilder(Protocol):
    """Renders the post-confirmation receipt image for a successful execution.

    Concrete implementation lives in channel/receipt/ (Python + playwright,
    see AGENTS.md's Module Placement Log) and is wired in runtime/
    dependencies.py, same convention as ExecutionDispatcher. Must never
    raise — a rendering failure degrades to a text-only confirmation, it
    must never break the confirm flow itself."""

    async def build(
        self,
        confirmed: ConfirmedActionV2,
        execution: ExecutionResult,
        actor: ActorIdentity | None,
        *,
        saved: bool = False,
    ) -> bytes | None: ...
