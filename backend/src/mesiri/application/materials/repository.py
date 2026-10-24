"""Material execution repository port (M8).

Defines the contract for persisting a confirmed Material command's outcome
without coupling to a specific implementation (PostgreSQL, fake, etc.).
Every method takes an externally-supplied connection — the repository never
opens an engine and never commits; the Application Handler owns the one
transaction (backend capability-boundary + transaction-ownership rules).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from mesiri_contracts.application.commands.material import (
    RecordMaterialReceiptCommand,
    RecordMaterialTransferCommand,
    RecordMaterialUsageCommand,
)
from mesiri_contracts.application.results.execution_result import ExecutionResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

MaterialCommand = (
    RecordMaterialReceiptCommand | RecordMaterialUsageCommand | RecordMaterialTransferCommand
)


class MaterialExecutionRepository(ABC):
    """Persists Material command execution outcomes against a supplied connection."""

    @abstractmethod
    async def check_idempotency(self, conn: AsyncConnection, key: str) -> ExecutionResult | None:
        """Return the cached ExecutionResult if `key` was already claimed, else None."""
        ...

    async def check_rules(self, conn: AsyncConnection, cmd: MaterialCommand) -> list[str]:
        """Stock rules that refuse a save (reasons), checked in the Handler's
        transaction before ``persist_success``. None by default."""
        return []

    @abstractmethod
    async def persist_success(self, conn: AsyncConnection, cmd: MaterialCommand) -> ExecutionResult:
        """Claim the idempotency key, insert the material row + outbox event, cache
        SUCCEEDED, and transition the workflow to COMPLETED — all against `conn`."""
        ...

    @abstractmethod
    async def persist_rejection(
        self, conn: AsyncConnection, cmd: MaterialCommand, reasons: list[str]
    ) -> ExecutionResult:
        """Claim the idempotency key, cache REJECTED (no material/outbox row), and
        transition the workflow to EXECUTION_REJECTED — all against `conn`."""
        ...
