"""WA-57: the parts of a message that are not done yet.

Live 23 Oct: "holo bricks came, the scaffolders and plasterers were there" got
one question (how many bricks?), and once the bricks were saved the labour part
was gone. A part held behind another question went to ``toolbox.held``, which
nothing read, and a part the model could not record yet (no count) was simply
dropped.

Now each such part is kept here, per sender (Redis, like the card):

* a save call held behind a waiting question goes in by itself;
* the model notes any other part with the ``still_to_do`` tool, or in the
  ``other_parts`` of its ``ask_user`` question (WA-58: required, so every
  question accounts for the rest of the message);
* every turn shows the numbered list to the model (``context_line``);
* a part leaves the list when a save of its tool names it (WA-58: matched by
  its words, so saving the cement does not clear the holo bricks), or when the
  model drops it (already recorded, or they said it is not needed);
* right after the Save tap, the first part not yet asked about is asked
  (``ask_next``, ``follow_up_text``); it stays on the list until it is saved
  or dropped, and the rest wait for the next Save.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from typing import Any

_log = logging.getLogger("mesiri.agent")

#: A part nobody came back to within this time is dropped.
LATER_TTL_SECONDS = 6 * 60 * 60
MAX_ITEMS = 4
NOTE_LIMIT = 160
#: The follow-up's own words start with this; the reply language then follows
#: the sender's earlier messages (prompt.reply_letters_rule).
FOLLOW_UP_PREFIX = "(They tapped Save."

_WORD = re.compile(r"[a-z]{4,}")
#: Words that say nothing about WHICH part it is (and the held calls' own keys).
_PLAIN = frozenset(
    """came come comes count there were with have from that they them their still need needs
    said site today yesterday tomorrow workers worker trade name headcount material quantity unit
    date project attendance status present absent number numbers load loads bags nos""".split()
)


@dataclass(frozen=True, slots=True)
class LaterItem:
    #: The save tool that will record it ("" when the model could not tell).
    tool: str
    #: What they said about it, in a few English words.
    note: str
    #: How many times the system asked for it after a Save (WA-58).
    asked: int = 0

    def line(self) -> str:
        return f"{self.note} ({self.tool})" if self.tool else self.note


def held_item(name: str, args: dict[str, Any]) -> LaterItem:
    """A save call held behind a waiting question, as a part still to do."""
    shown = {k: v for k, v in args.items() if v not in (None, "", [], {})}
    return LaterItem(name, _cut(json.dumps(shown, ensure_ascii=False, default=str)))


def _cut(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= NOTE_LIMIT else text[: NOTE_LIMIT - 1] + "…"


def _squash(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def same_part(a: str, b: str) -> bool:
    """Whether two descriptions name the same thing: a word of one (4+ letters,
    not a plain word) inside the other, ignoring spaces -- "Holobricks 100 nos"
    and "holo bricks came", "4 scaffolder" and "scaffolders and plasterers"."""
    squashed_a, squashed_b = _squash(a), _squash(b)
    if squashed_a == squashed_b:
        return True
    words_a = set(_WORD.findall((a or "").lower())) - _PLAIN
    words_b = set(_WORD.findall((b or "").lower())) - _PLAIN
    return any(w in squashed_b for w in words_a) or any(w in squashed_a for w in words_b)


def merged(
    current: list[LaterItem],
    *,
    saved: list[tuple[str, str]],
    added: list[LaterItem],
    drop: set[int] | frozenset[int] = frozenset(),
) -> list[LaterItem]:
    """The list after a turn, oldest first. ``drop`` are 1-based numbers of
    ``current`` the model said are done or not needed; each ``(tool, what was
    saved)`` takes off the one part of that tool it names; a new part replaces
    one that names the same thing with the same tool."""
    items = [i for n, i in enumerate(current, 1) if n not in drop]
    for tool, summary in saved:
        for i in items:
            if i.tool == tool and same_part(i.note, summary):
                items.remove(i)
                break
    for new in added:
        note = _cut(new.note)
        if not note:
            continue
        twin = next((i for i in items if _twin(i, new.tool, note)), None)
        asked = twin.asked if twin is not None else 0
        if twin is not None:
            items.remove(twin)
        items.append(LaterItem(new.tool, note, asked))
    return items[-MAX_ITEMS:]


def _twin(item: LaterItem, tool: str, note: str) -> bool:
    if item.note.lower() == note.lower():
        return True
    return bool(tool) and item.tool == tool and same_part(item.note, note)


def context_line(items: list[LaterItem]) -> str | None:
    if not items:
        return None
    listed = "; ".join(f"{n}. {i.line()}" for n, i in enumerate(items, 1))
    return (
        f"Still to do from their earlier messages (not recorded yet, already noted): {listed}. "
        "When this message does not need your question or their Save first, take the first one: "
        "record it with its tool, or ask_user for what is missing. One that is already recorded, "
        "or that they say is not needed, goes with still_to_do drop [its number]. Never ask for "
        "something they already said."
    )


def follow_up_text(item: LaterItem) -> str:
    return (
        f"{FOLLOW_UP_PREFIX} Their earlier message also had, not recorded yet: {item.line()}. "
        "Take it now: record it with its tool if every detail is known, else ask_user ONE "
        "short question for what is missing.)"
    )


class LaterStore:
    """Per sender, the parts still to do (Redis, like the card)."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _key(actor: Any) -> str | None:
        org = getattr(actor, "organization_id", None)
        user = getattr(actor, "user_id", None)
        return f"{org}:user:{user}:agent_later" if org and user else None

    async def get(self, actor: Any) -> list[LaterItem]:
        key = self._key(actor)
        if key is None:
            return []
        try:
            raw = await self._redis.get_json(key)
        except Exception:  # noqa: BLE001 -- an empty list is the safe answer
            _log.warning("agent.later_read_failed", exc_info=True)
            return []
        items: list[LaterItem] = []
        for row in raw or []:
            if isinstance(row, dict) and row.get("note"):
                asked = row.get("asked")
                items.append(
                    LaterItem(str(row.get("tool") or ""), str(row["note"]), asked if isinstance(asked, int) else 0)
                )
        return items

    async def put(self, actor: Any, items: list[LaterItem]) -> None:
        key = self._key(actor)
        if key is None:
            return
        try:
            if items:
                rows = [{"tool": i.tool, "note": i.note, "asked": i.asked} for i in items]
                await self._redis.set_json(key, rows, ttl_seconds=LATER_TTL_SECONDS)
            else:
                await self._redis.delete(self._redis.namespaced(key))
        except Exception:  # noqa: BLE001 -- the list is a reminder, never a record
            _log.warning("agent.later_write_failed", exc_info=True)

    async def ask_next(self, actor: Any) -> LaterItem | None:
        """The first part not yet asked about after a Save, marked as asked. It
        stays on the list until a save names it or the model drops it."""
        items = await self.get(actor)
        for n, item in enumerate(items):
            if item.asked == 0:
                items[n] = replace(item, asked=1)
                await self.put(actor, items)
                return item
        return None
