"""``change_or_undo``: undo or change anything saved, from the journal
(request 142, B). One service for every kind of fact.

- ``request``: what the sender said ("last", an id, or words like "the cement")
  is matched against their own recent journal entries; an undo is ALWAYS asked
  first -- a confirm card with the lines and two buttons. Nothing is removed
  here. Several matches become a pick list.
- ``confirm``: the Yes tap removes exactly those facts through each module's own
  undo (``gw.undo_facts``) and marks them undone in the journal; Keep leaves
  everything as it is.
- a change (``changes`` given) is the existing correction: a "Change ..." line on
  the card, saved by tap (``draft_flow.change_saved``), starting from the
  arguments the journal kept.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from channel.replies import ReplySpec

from . import journal as jr
from .cards import CardItem
from .gateway import StepResult

_log = logging.getLogger("mesiri.agent")


def _owner(gw: Any) -> tuple[str, str]:
    return str(gw.actor.organization_id), str(gw.actor.user_id)


async def recent(gw: Any) -> list[jr.JournalEntry]:
    if gw.journal is None or gw.actor is None:
        return []
    org, user = _owner(gw)
    return await gw.journal.recent(org, user)


async def request(gw: Any, ref: str, changes: dict[str, Any] | None = None) -> StepResult:
    """The confirm card for an undo (or the correction line for a change)."""
    entries = await recent(gw)
    target, options = jr.pick(entries, ref)
    if target is None and options:
        return StepResult("choose", text="Which one should be removed?", reply=jr.choose_reply(options))
    if target is None:
        return StepResult("info", text=jr.NOTHING if not entries else "I couldn't find that among what you saved lately.")
    if changes:
        return await _change(gw, target, changes)
    return StepResult(
        "choose",
        text="Asked them to confirm removing it.",
        reply=jr.confirm_reply(target),
        awaiting="confirm_undo",
    )


async def _change(gw: Any, target: jr.Target, changes: dict[str, Any]) -> StepResult:
    if len(target.numbers) != 1:
        return StepResult("info", text="Tell me which of those to change.")
    fact = target.facts[0]
    try:
        uuid.UUID(fact.fact_id)
    except ValueError:
        return StepResult("error", text="That one cannot be changed here, so nothing was changed.")
    item = CardItem(fact.tool, dict(fact.args), fact.fact_type, fact.fact_id, fact.line)
    return await gw.change_saved_item(item, changes)


async def confirm(gw: Any, action: str, entry_id: str, numbers: list[int] | None) -> ReplySpec:
    """The tap on the confirm card or on a pick-list row."""
    org, user = _owner(gw)
    entry = await gw.journal.get(entry_id, org, user)
    if entry is None or entry.expired():
        return ReplySpec(text=jr.EXPIRED)
    if action == jr.KEEP:
        return ReplySpec(text=jr.KEPT)
    wanted = numbers or [i for i, _f in enumerate(entry.facts, 1)]
    picked = [entry.facts[n - 1] for n in wanted if 1 <= n <= len(entry.facts)]
    live = [f for f in picked if not f.undone]
    if not live:
        return ReplySpec(text=jr.GONE)
    if gw.undo_facts is None:
        return ReplySpec(text="I can't remove that here yet.")
    facts: list[tuple[str, uuid.UUID]] = []
    for fact in live:
        try:
            facts.append((fact.fact_type, uuid.UUID(fact.fact_id)))
        except ValueError:
            continue
    undone = await gw.undo_facts(facts)
    done_ids = {str(f[1]) for f in (getattr(undone, "done", None) or [])}
    gone = [f for f in live if f.fact_id in done_ids or str(uuid.UUID(f.fact_id)) in done_ids]
    refused = list(getattr(undone, "refused", None) or [])
    if gone:
        await gw.journal.mark_undone(entry.id, org, user, [f.fact_id for f in gone])
        await _drop_from_card(gw, gone)
        _log.info("journal.undone entry=%s facts=%s", entry.id, len(gone))
    if not gone and not refused:
        return ReplySpec(text=jr.GONE)
    parts = []
    if gone:
        parts.append("✅ Removed: " + "; ".join(jr.line_of(entry, f) for f in gone))
    if refused:
        parts.append(f"Couldn't remove {len(refused)}: {refused[0]}.")
    return ReplySpec(text="\n".join(parts))


async def _drop_from_card(gw: Any, gone: list[jr.JournalFact]) -> None:
    """The old per-card store (until it is removed) must not offer what is gone."""
    if gw.cards is None:
        return
    try:
        await gw.cards.drop(gw.actor, [(f.fact_type, uuid.UUID(f.fact_id)) for f in gone])
    except Exception:  # noqa: BLE001 -- the card store only lingers
        _log.warning("journal.card_drop_failed", exc_info=True)
