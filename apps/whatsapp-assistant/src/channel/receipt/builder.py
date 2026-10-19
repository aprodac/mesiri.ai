"""Concrete ReceiptBuilder — satisfies interactions.ports.ReceiptBuilder.

The only place that wires ConfirmedActionV2 + ExecutionResult + ActorIdentity
into the pure data.py mapper, then the template + renderer. Catches every
exception (the port's contract: never break the confirm flow over a
rendering failure) and returns None to degrade to a text-only confirmation.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .data import ReceiptData, build_receipt_data, card_texts, combine_receipts, with_card_texts
from .render import ReceiptRenderer
from .template import render_html

logger = logging.getLogger(__name__)


class RecordReceiptBuilder:
    """Builds the receipt card for ANY confirmed record.

    Named for materials once, when that was all there was. It has since served
    expense, and now labour attendance -- so the old name pointed anyone
    debugging a wrong-looking expense or attendance receipt away from the one
    file that renders it. `build_receipt_data` branches per action type; this
    class is type-agnostic.
    """

    def __init__(
        self,
        renderer: ReceiptRenderer,
        localize: Callable[[list[str], Any], Awaitable[dict[str, str]]] | None = None,
    ) -> None:
        self._renderer = renderer
        #: ``(texts, actor) -> {english: translated}``: the card's free text in
        #: the sender's language and letters (request 57, B4). Never raises;
        #: an empty result leaves the card in English.
        self._localize = localize

    async def build(self, confirmed: ConfirmedActionV2, execution: ExecutionResult, actor) -> bytes | None:
        return await self.build_combined([(confirmed, execution)], actor)

    async def build_combined(
        self, saved: list[tuple[ConfirmedActionV2, ExecutionResult]], actor
    ) -> bytes | None:
        """One card for one or several records saved from the same message:
        a single record gets its full card, several get a row each."""
        parts: list[ReceiptData] = []
        now = datetime.now(UTC)
        for confirmed, execution in saved:
            if execution.status not in (ExecutionStatus.SUCCEEDED, ExecutionStatus.ALREADY_EXECUTED):
                continue
            if execution.material_row_id is None:
                continue
            try:
                parts.append(self._data(confirmed, execution, actor, now))
            except Exception:
                logger.exception(
                    "receipt.render_failed correlation_id=%s workflow_instance_id=%s",
                    confirmed.correlation_id,
                    confirmed.workflow_instance_id,
                )
        if not parts:
            return None
        parts = await self._localized(parts, actor)
        try:
            return await self._renderer.render_png(render_html(combine_receipts(parts)))
        except Exception:
            logger.exception("receipt.render_failed parts=%s", len(parts))
            return None

    async def _localized(self, parts: list[ReceiptData], actor: Any) -> list[ReceiptData]:
        if self._localize is None:
            return parts
        try:
            texts = [t for part in parts for t in card_texts(part)]
            translated = await self._localize(texts, actor) if texts else {}
            return [with_card_texts(part, translated) for part in parts] if translated else parts
        except Exception:  # noqa: BLE001 -- the card goes out in English
            logger.warning("receipt.localize_failed", exc_info=True)
            return parts

    @staticmethod
    def _data(
        confirmed: ConfirmedActionV2, execution: ExecutionResult, actor: Any, now: datetime
    ) -> ReceiptData:
        return build_receipt_data(
            confirmed.draft_action,
            record_row_id=execution.material_row_id,
            reporter_name=actor.full_name if actor else None,
            projects=actor.projects if actor else [],
            sites=actor.sites if actor else [],
            confirmed_at=now,
            timezone=getattr(actor, "timezone", None),
        )
