"""The save journal (request 142, B): one entry per Save, whatever it saved.

Every Save tap writes ONE journal entry in the same transaction as the records
(company, sender, time, site, day, and a reference to each fact written). "Undo"
and "change" of anything saved read the journal, never a per-type store, so they
work the same for labour, work, materials, issues, expenses and transfers.

This module is the entry, the matching of what the sender said against it, the
confirm card (an undo is always asked first) and the two stores:

- ``MemoryJournalStore``: tests, and a deployment with no database;
- ``PostgresJournalStore``: the ``save_journal`` table (migration 0493), tenant
  isolated by row-level security AND by every query naming the company and the
  sender -- a sender can only ever undo their own entries.

The taps are ``agj:<undo|keep>:<entry id>[:<fact numbers>]``.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from channel.replies import ListRow, ReplySpec
from runtime.save_first import canonical_uuid

TAP_PREFIX = "agj:"
UNDO = "undo"
KEEP = "keep"

#: An entry stays undoable this long; older ones are the dashboard's to fix.
UNDO_WINDOW_SECONDS = 3 * 24 * 3600
#: How many recent entries are looked through.
RECENT = 10

YES_TITLE = "✅ Yes, remove"
KEEP_TITLE = "↩️ Keep it"

#: Typed to the confirm card instead of tapping (English, Manglish, Malayalam, Hindi).
YES_WORDS = frozenset(
    "yes y yeah yep ok okay sure remove delete haan ha han ho athe aanu aa sheri shari seri venam kalayu കളയൂ ശരി അതെ हाँ हां".split()
)
NO_WORDS = frozenset("no n nope keep dont cancel venda vendaa illa nahi nahin ഇല്ല വേണ്ട नहीं".split())

NOTHING = "Nothing saved by you recently, so there is nothing to undo."
KEPT = "👍 Okay, kept as it is."
GONE = "That one is already removed. Nothing more to undo."
EXPIRED = "That has expired. Ask me again if you still want something removed."


@dataclass(slots=True)
class JournalFact:
    fact_type: str
    fact_id: str
    #: The tool and arguments that made it (a change starts from them).
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    #: The card line as saved.
    line: str = ""
    undone: bool = False


@dataclass(slots=True)
class JournalEntry:
    organization_id: str
    user_id: str
    facts: list[JournalFact]
    draft_id: str = ""
    site_id: str = ""
    site: str = ""
    #: The day the records are for (ISO date), when the Save knows it.
    day: str = ""
    created: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def live(self) -> list[JournalFact]:
        return [f for f in self.facts if not f.undone]

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) - self.created > UNDO_WINDOW_SECONDS

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> JournalEntry:
        facts = row["facts"]
        if isinstance(facts, str):
            facts = json.loads(facts)
        return cls(
            id=uuid.UUID(str(row["id"])).hex,
            organization_id=str(row["organization_id"]),
            user_id=str(row["user_id"]),
            draft_id=uuid.UUID(str(row["draft_id"])).hex if row["draft_id"] else "",
            site_id=str(row["site_id"]) if row["site_id"] else "",
            site=str(row["site_name"] or ""),
            day=str(row["day"]) if row["day"] else "",
            created=float(row["created_epoch"]),
            facts=[JournalFact(**f) for f in facts or []],
        )


class JournalStore(Protocol):
    async def record(self, entry: JournalEntry) -> None:
        """Keep the entry (inside the Save's transaction)."""
        ...

    async def recent(self, organization_id: Any, user_id: Any, limit: int = RECENT) -> list[JournalEntry]:
        """The sender's own entries with something left to undo, newest first."""
        ...

    async def get(self, entry_id: str, organization_id: Any, user_id: Any) -> JournalEntry | None:
        """The sender's own entry by id."""
        ...

    async def mark_undone(self, entry_id: str, organization_id: Any, user_id: Any, fact_ids: list[str]) -> None:
        ...


class MemoryJournalStore:
    def __init__(self) -> None:
        self.rows: dict[str, JournalEntry] = {}

    @staticmethod
    def _mine(entry: JournalEntry, organization_id: Any, user_id: Any) -> bool:
        return entry.organization_id == str(organization_id) and entry.user_id == str(user_id)

    async def record(self, entry: JournalEntry) -> None:
        self.rows[entry.id] = _copy(entry)

    async def recent(self, organization_id: Any, user_id: Any, limit: int = RECENT) -> list[JournalEntry]:
        mine = [e for e in self.rows.values() if self._mine(e, organization_id, user_id) and e.live and not e.expired()]
        return [_copy(e) for e in sorted(mine, key=lambda e: e.created, reverse=True)[:limit]]

    async def get(self, entry_id: str, organization_id: Any, user_id: Any) -> JournalEntry | None:
        entry = self.rows.get(entry_id)
        return _copy(entry) if entry is not None and self._mine(entry, organization_id, user_id) else None

    async def mark_undone(self, entry_id: str, organization_id: Any, user_id: Any, fact_ids: list[str]) -> None:
        entry = self.rows.get(entry_id)
        if entry is None or not self._mine(entry, organization_id, user_id):
            return
        for fact in entry.facts:
            if fact.fact_id in fact_ids:
                fact.undone = True


def _copy(entry: JournalEntry) -> JournalEntry:
    return JournalEntry(
        organization_id=entry.organization_id,
        user_id=entry.user_id,
        facts=[JournalFact(**asdict(f)) for f in entry.facts],
        draft_id=entry.draft_id,
        site_id=entry.site_id,
        site=entry.site,
        day=entry.day,
        created=entry.created,
        id=entry.id,
    )


class PostgresJournalStore:
    """``save_journal`` through ``PostgresDatabase.transaction()``: inside the
    Save's ``shared_transaction()`` the write joins it."""

    def __init__(self, db: Any) -> None:
        self._db = db

    _COLUMNS = (
        "id, organization_id, user_id, draft_id, site_id, site_name, day, facts, "
        "EXTRACT(EPOCH FROM created_at) AS created_epoch"
    )

    async def record(self, entry: JournalEntry) -> None:
        from sqlalchemy import text

        params = {
            "id": uuid.UUID(hex=entry.id),
            "org": canonical_uuid(entry.organization_id),
            "user": canonical_uuid(entry.user_id),
            "draft": canonical_uuid(entry.draft_id),
            "site": canonical_uuid(entry.site_id),
            "site_name": entry.site or None,
            "day": entry.day or None,
            "facts": json.dumps([asdict(f) for f in entry.facts], default=str),
        }
        async with self._db.transaction() as conn:
            await conn.execute(
                text(
                    "INSERT INTO save_journal (id, organization_id, user_id, draft_id, site_id, site_name, day, facts) "
                    "VALUES (:id, :org, :user, :draft, :site, :site_name, CAST(:day AS date), CAST(:facts AS jsonb))"
                ),
                params,
            )

    async def recent(self, organization_id: Any, user_id: Any, limit: int = RECENT) -> list[JournalEntry]:
        from sqlalchemy import text

        org, user = canonical_uuid(organization_id), canonical_uuid(user_id)
        if org is None or user is None:
            return []
        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"SELECT {self._COLUMNS} FROM save_journal WHERE organization_id = :org AND user_id = :user "
                        "AND created_at > now() - make_interval(secs => :window) "
                        "AND EXISTS (SELECT 1 FROM jsonb_array_elements(facts) f WHERE NOT COALESCE((f->>'undone')::boolean, false)) "
                        "ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"org": org, "user": user, "window": UNDO_WINDOW_SECONDS, "limit": limit},
                )
            ).mappings().all()
        return [JournalEntry.from_row(r) for r in rows]

    async def get(self, entry_id: str, organization_id: Any, user_id: Any) -> JournalEntry | None:
        from sqlalchemy import text

        org, user = canonical_uuid(organization_id), canonical_uuid(user_id)
        try:
            ident = uuid.UUID(hex=entry_id)
        except ValueError:
            return None
        if org is None or user is None:
            return None
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {self._COLUMNS} FROM save_journal "
                        "WHERE id = :id AND organization_id = :org AND user_id = :user"
                    ),
                    {"id": ident, "org": org, "user": user},
                )
            ).mappings().first()
        return JournalEntry.from_row(row) if row is not None else None

    async def mark_undone(self, entry_id: str, organization_id: Any, user_id: Any, fact_ids: list[str]) -> None:
        entry = await self.get(entry_id, organization_id, user_id)
        if entry is None:
            return
        from sqlalchemy import text

        for fact in entry.facts:
            if fact.fact_id in fact_ids:
                fact.undone = True
        done = not entry.live
        async with self._db.transaction() as conn:
            await conn.execute(
                text(
                    "UPDATE save_journal SET facts = CAST(:facts AS jsonb), "
                    "undone_at = CASE WHEN :done THEN now() ELSE undone_at END "
                    "WHERE id = :id AND organization_id = :org AND user_id = :user"
                ),
                {
                    "facts": json.dumps([asdict(f) for f in entry.facts], default=str),
                    "done": done,
                    "id": uuid.UUID(hex=entry_id),
                    "org": canonical_uuid(organization_id),
                    "user": canonical_uuid(user_id),
                },
            )


# -- taps -----------------------------------------------------------------------


def tap_id(action: str, entry_id: str, numbers: list[int] | None = None) -> str:
    tail = ["all"] if not numbers else [",".join(str(n) for n in numbers)]
    return ":".join([f"{TAP_PREFIX}{action}", entry_id, *(tail if action == UNDO else [])])


def parse_tap(value: str) -> tuple[str, str, list[int] | None] | None:
    """(action, entry id, fact numbers or None for all) from a tap id."""
    if not value.startswith(TAP_PREFIX):
        return None
    action, _, rest = value[len(TAP_PREFIX):].partition(":")
    entry_id, _, tail = rest.partition(":")
    if action not in (UNDO, KEEP) or len(entry_id) != 32:
        return None
    try:
        uuid.UUID(hex=entry_id)
    except ValueError:
        return None
    if action == KEEP or tail in ("", "all"):
        return action, entry_id, None
    try:
        return action, entry_id, [int(n) for n in tail.split(",")]
    except ValueError:
        return None


# -- what the sender meant ------------------------------------------------------

_WORD = re.compile(r"[a-z0-9ഀ-ൿऀ-ॿ]+", re.IGNORECASE)
#: Said when they mean the last thing, not a particular one.
_LAST = {"", "last", "latest", "that", "it", "this", "recent"}
_STOP = frozenset(
    "the a an of in on for to and my that this it last latest remove delete undo cancel entry card save saved "
    "please ath athu aa ee ente".split()
)


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(text or "")} - _STOP


def _score(said: set[str], entry: JournalEntry, fact: JournalFact) -> int:
    have = _words(" ".join([fact.line, fact.tool.replace("_", " "), entry.site]))
    # a stem match counts ("masons" ~ "mason")
    return sum(1 for w in said if any(w == h or (len(w) > 3 and (w.startswith(h) or h.startswith(w))) for h in have if len(h) > 2))


@dataclass(slots=True)
class Target:
    """What an undo will remove: facts (by their number in the entry) of one entry."""

    entry: JournalEntry
    numbers: list[int]

    @property
    def facts(self) -> list[JournalFact]:
        return [self.entry.facts[n - 1] for n in self.numbers]


def pick(entries: list[JournalEntry], ref: str) -> tuple[Target | None, list[Target]]:
    """The target for ``ref``: ("last", an entry id prefix, or a description).
    Returns (the one target, []) or (None, the candidates to choose from when
    the description fits several) or (None, []) when nothing fits."""
    if not entries:
        return None, []
    said = (ref or "").strip()
    if said.casefold() in _LAST:
        newest = entries[0]
        return Target(newest, [i for i, f in enumerate(newest.facts, 1) if not f.undone]), []
    for entry in entries:
        if said.casefold() == entry.id[:6]:
            return Target(entry, [i for i, f in enumerate(entry.facts, 1) if not f.undone]), []
    words = _words(said)
    if not words:
        return None, []
    scored: list[tuple[int, Target]] = []
    for entry in entries:
        for n, fact in enumerate(entry.facts, 1):
            if fact.undone:
                continue
            if (score := _score(words, entry, fact)) > 0:
                scored.append((score, Target(entry, [n])))
    if not scored:
        return None, []
    best = max(score for score, _t in scored)
    top = [t for score, t in scored if score == best]
    # the same line saved twice in a row is one question: take the newest
    return (top[0], []) if len(top) == 1 else (None, top[:5])


def line_of(entry: JournalEntry, fact: JournalFact) -> str:
    where = f" · {entry.site}" if entry.site and entry.site not in fact.line else ""
    return f"{fact.line}{where}"


def confirm_reply(target: Target) -> ReplySpec:
    """The one card an undo starts with: what would be removed, and two buttons.
    Nothing is removed before the Yes."""
    lines = "\n".join(f"• {line_of(target.entry, f)}" for f in target.facts)
    head = "Remove this?" if len(target.numbers) == 1 else f"Remove these {len(target.numbers)}?"
    return ReplySpec(
        text=f"{head}\n{lines}",
        buttons=(
            ListRow(tap_id(UNDO, target.entry.id, target.numbers), YES_TITLE),
            ListRow(tap_id(KEEP, target.entry.id), KEEP_TITLE),
        ),
    )


def choose_reply(targets: list[Target]) -> ReplySpec:
    """Several entries fit the description: which one? (each row asks the
    confirm card for exactly that line)."""

    def cut(text: str, limit: int) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    rows = tuple(
        ListRow(
            tap_id(UNDO, t.entry.id, t.numbers),
            cut(t.facts[0].line, 24),
            cut(line_of(t.entry, t.facts[0]), 72),
        )
        for t in targets
    )
    return ReplySpec(text="Which one should I remove?", list_button_label="Choose one", list_rows=rows)


def context_line(entries: list[JournalEntry]) -> str | None:
    """What the model is told about what the sender saved lately."""
    if not entries:
        return None
    last = entries[0]
    listed = "; ".join(f"{n}. {f.line}" for n, f in enumerate(last.facts, 1) if not f.undone)
    return (
        f"Their latest save {last.id[:6]}: {listed}. To remove or change anything they saved, call change_or_undo: "
        "it asks them to confirm first. Never say something was removed until it says so."
    )
