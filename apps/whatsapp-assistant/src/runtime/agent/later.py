"""WA-57: the parts of a message that are not done yet.

Live 23 Oct: "holo bricks came, the scaffolders and plasterers were there" got
one question (how many bricks?), and once the bricks were saved the labour part
was gone. A part held behind another question went to ``toolbox.held``, which
nothing read, and a part the model could not record yet (no count) was simply
dropped.

Now each such part is kept here, per sender (Redis, like the card):

* a save call held behind a waiting question goes in by itself;
* the model notes any other part with the ``still_to_do`` tool;
* every turn shows the list to the model (``context_line``);
* a part leaves the list when its save tool saves;
* right after the Save tap, its first part is taken (``take_first``) and the
  agent runs once more on it (``follow_up_text``), so it is asked at once;
  the rest wait for the next Save.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger("mesiri.agent")

#: A part nobody came back to within this time is dropped.
LATER_TTL_SECONDS = 6 * 60 * 60
MAX_ITEMS = 4
NOTE_LIMIT = 160
#: The follow-up's own words start with this; the reply language then follows
#: the sender's earlier messages (prompt.reply_letters_rule).
FOLLOW_UP_PREFIX = "(They tapped Save."


@dataclass(frozen=True, slots=True)
class LaterItem:
    #: The save tool that will record it ("" when the model could not tell).
    tool: str
    #: What they said about it, in a few English words.
    note: str

    def line(self) -> str:
        return f"{self.note} ({self.tool})" if self.tool else self.note


def held_item(name: str, args: dict[str, Any]) -> LaterItem:
    """A save call held behind a waiting question, as a part still to do."""
    shown = {k: v for k, v in args.items() if v not in (None, "", [], {})}
    return LaterItem(name, _cut(json.dumps(shown, ensure_ascii=False, default=str)))


def _cut(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= NOTE_LIMIT else text[: NOTE_LIMIT - 1] + "…"


def merged(
    current: list[LaterItem], *, saved_tools: set[str], added: list[LaterItem]
) -> list[LaterItem]:
    """The list after a turn: what its saves covered goes, its new parts come
    in (one per save tool, the newest wording winning), oldest first."""
    items = [i for i in current if not (i.tool and i.tool in saved_tools)]
    for new in added:
        note = _cut(new.note)
        if not note:
            continue
        new = LaterItem(new.tool, note)
        items = [
            i for i in items
            if not ((new.tool and i.tool == new.tool) or i.note.lower() == note.lower())
        ]
        items.append(new)
    return items[-MAX_ITEMS:]


def context_line(items: list[LaterItem]) -> str | None:
    if not items:
        return None
    listed = "; ".join(f"{n}. {i.line()}" for n, i in enumerate(items, 1))
    return (
        f"Still to do from their earlier message (not recorded yet): {listed}. When this message "
        "does not need your question or their Save first, take the first one: record it with its "
        "tool, or ask_user for what is missing. Never ask for something they already said."
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
                items.append(LaterItem(str(row.get("tool") or ""), str(row["note"])))
        return items

    async def put(self, actor: Any, items: list[LaterItem]) -> None:
        key = self._key(actor)
        if key is None:
            return
        try:
            if items:
                rows = [{"tool": i.tool, "note": i.note} for i in items]
                await self._redis.set_json(key, rows, ttl_seconds=LATER_TTL_SECONDS)
            else:
                await self._redis.delete(self._redis.namespaced(key))
        except Exception:  # noqa: BLE001 -- the list is a reminder, never a record
            _log.warning("agent.later_write_failed", exc_info=True)

    async def take_first(self, actor: Any) -> LaterItem | None:
        """The oldest part, off the list: the follow-up turn asks for it."""
        items = await self.get(actor)
        if not items:
            return None
        await self.put(actor, items[1:])
        return items[0]
