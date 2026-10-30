"""The sender's latest card, kept by code (request 88).

A reply that saved entries carries a card: the "To save:" list with Save and
Cancel. The code remembers that card per sender (Redis, a few hours) so that
what follows is decided by it, never by the model's guess:

- "undo that" removes the entries of the latest card -- the ids it may name
  are the ones listed to it in its context, and the adapter rejects any other;
- "alla, 8 mason aanu" changes one item of the card that is still open (not
  yet saved): ``update_pending_card`` merges the change into that item's own
  tool arguments, withdraws the old draft and saves the new one, then the
  same card is shown again with Save and Cancel.

State of a card: ``open`` (waiting for Save / Cancel), ``saved`` (the sender
tapped Save), ``legacy`` (a reply whose entries have no Save button -- the old
Undo button stays for those and ``undo_last`` keeps its old behaviour).
Cancel removes the card.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

_log = logging.getLogger("mesiri.agent")

#: As long as the sender may still undo (runtime/save_first.UNDO_WINDOW_HOURS).
CARD_TTL_SECONDS = 6 * 60 * 60

OPEN = "open"
SAVED = "saved"
LEGACY = "legacy"


@dataclass(slots=True)
class CardItem:
    """One entry on a card: what the tool was called with, and the record it made."""

    tool: str
    args: dict[str, Any]
    fact_type: str
    fact_id: str
    summary: str

    @property
    def ref(self) -> str:
        """The short id the model may name an item by (the code lists it)."""
        return uuid.UUID(self.fact_id).hex[:8]

    @property
    def fact(self) -> tuple[str, uuid.UUID]:
        return self.fact_type, uuid.UUID(self.fact_id)

    @property
    def day(self) -> str:
        """The day the entry is for, as the sender would say it."""
        stated = str(self.args.get("date") or "").strip()
        return stated if stated and stated.lower() != "today" else "today"


@dataclass(slots=True)
class Card:
    id: str
    state: str
    items: list[CardItem] = field(default_factory=list)
    created: float = 0.0
    #: The one site every entry is for, so "✅ Saved" can name it (request 116).
    site: str = ""
    #: Request 159 (E): the draft a partial Save left with what still waits, so its
    #: Cancel can say what stayed saved.
    rest: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Any) -> Card | None:
        try:
            items = [CardItem(**item) for item in raw.get("items", [])]
            return cls(
                id=str(raw["id"]),
                state=str(raw["state"]),
                items=items,
                created=float(raw.get("created", 0)),
                site=str(raw.get("site") or ""),
                rest=str(raw.get("rest") or ""),
            )
        except Exception:  # noqa: BLE001 -- an unreadable card is no card
            return None

    def by_ref(self, refs: list[str]) -> list[CardItem] | None:
        """The items these ids name, or None when any is not on this card."""
        found = []
        for ref in refs:
            item = next((i for i in self.items if i.ref == str(ref).strip().lower()), None)
            if item is None:
                return None
            if item not in found:
                found.append(item)
        return found


def new_card(state: str, items: list[CardItem], site: str = "") -> Card:
    return Card(id=uuid.uuid4().hex[:6], state=state, items=items, created=time.time(), site=site)


def removed_line(items: list[CardItem]) -> str:
    """"Removed: 2 painters (today)" -- what was undone, from the saved data."""
    return "Removed: " + "; ".join(f"{i.summary} ({i.day})" for i in items)


def context_line(card: Card | None) -> str | None:
    """What the model is told about the sender's latest card: its id and
    items, and which tool may touch it."""
    if card is None or card.state == LEGACY or not card.items:
        return None
    if card.state == OPEN:
        listed = "; ".join(f"{n}. {i.summary}" for n, i in enumerate(card.items, 1))
        return (
            f"Their open card {card.id} (Save / Cancel not tapped yet): {listed}. To change an item "
            f"of it, call update_pending_card with card_id {card.id}; undo_last cancels it."
        )
    listed = "; ".join(f"[{i.ref}] {i.summary}" for i in card.items)
    return (
        f"Their latest saved card: {listed}. undo_last removes it; name an entry by its id in "
        "brackets only when they mean just that entry."
    )


class CardStore:
    """Per sender, the latest card (Redis, like the other conversation hints)."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _key(actor: Any) -> str | None:
        org = getattr(actor, "organization_id", None)
        user = getattr(actor, "user_id", None)
        return f"{org}:user:{user}:agent_card" if org and user else None

    async def get(self, actor: Any) -> Card | None:
        key = self._key(actor)
        if key is None:
            return None
        try:
            raw = await self._redis.get_json(key)
        except Exception:  # noqa: BLE001 -- no card is the safe answer
            _log.warning("agent.card_read_failed", exc_info=True)
            return None
        return Card.from_json(raw) if raw else None

    async def put(self, actor: Any, card: Card) -> None:
        key = self._key(actor)
        if key is None:
            return
        try:
            await self._redis.set_json(key, card.to_json(), ttl_seconds=CARD_TTL_SECONDS)
        except Exception:  # noqa: BLE001 -- the card only enables undo / edit
            _log.warning("agent.card_write_failed", exc_info=True)

    async def clear(self, actor: Any) -> None:
        key = self._key(actor)
        if key is None:
            return
        try:
            await self._redis.delete(self._redis.namespaced(key))
        except Exception:  # noqa: BLE001
            _log.warning("agent.card_clear_failed", exc_info=True)

    async def settle(self, actor: Any, facts: list[tuple[str, uuid.UUID]], *, keep: bool) -> Card | None:
        """The sender tapped Save (``keep``) or Cancel on the card holding
        ``facts``: the card becomes saved, or goes. A tap on some other card
        changes nothing. Returns the card as it was."""
        card = await self.get(actor)
        if card is None or not card.items:
            return None
        if {i.fact for i in card.items} != set(facts):
            return None
        if keep:
            await self.put(actor, Card(card.id, SAVED, card.items, card.created, card.site))
        else:
            await self.clear(actor)
        return card

    async def drop(self, actor: Any, facts: list[tuple[str, uuid.UUID]]) -> None:
        """These entries were removed: take them off the card."""
        card = await self.get(actor)
        if card is None:
            return
        gone = set(facts)
        left = [i for i in card.items if i.fact not in gone]
        if len(left) == len(card.items):
            return
        if left:
            await self.put(actor, Card(card.id, card.state, left, card.created, card.site))
        else:
            await self.clear(actor)


def merge_changes(tool: str, args: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """``args`` with ``changes`` applied. A list of worker lines is merged by
    trade (or by name): "8 mason" replaces the mason line and leaves the
    helpers; a trade not on the card is added. Anything else replaces."""
    merged = {**args}
    for key, value in changes.items():
        if value is None:
            continue
        if key == "workers" and isinstance(value, list):
            merged[key] = _merge_workers(list(merged.get("workers") or []), value)
        else:
            merged[key] = value
    return merged


def _worker_key(line: dict[str, Any]) -> str:
    from mesiri.domains.workforce.workers import normalize_trade

    name = str(line.get("name") or "").strip().casefold()
    if name:
        return f"name:{name}"
    return f"trade:{normalize_trade(line.get('trade')) or ''}"


def _merge_workers(current: list[Any], changed: list[Any]) -> list[Any]:
    lines = [dict(x) if isinstance(x, dict) else x for x in current]
    for change in changed:
        if not isinstance(change, dict):
            continue
        key = _worker_key(change)
        for index, line in enumerate(lines):
            if isinstance(line, dict) and _worker_key(line) == key:
                # The line keeps its own trade and name spelling; the pipeline normalises it.
                lines[index] = {**line, **{k: v for k, v in change.items() if k not in ("trade", "name")}}
                break
        else:
            lines.append(dict(change))
    return lines
