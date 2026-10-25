"""The Save button on the agent's reply (WA-35).

Rule (Ilan, 21 Oct 2026): nothing a worker sends is kept until they tap Save
on a confirmation. The agent still saves through the existing save-first path
(WA-01), so every record is a DRAFT the moment it is written. Its reply then
shows those drafts under "To save:" -- the list is the system's, written from
the saved data, never the model's words -- with two buttons:

    ✅ Save    confirms exactly those drafts (BE-09 confirm, as the evening
               "Keep it" does)
    ❌ Cancel  rejects them through each module's own undo (BE-09 reject, as
               "Remove it" and UNDO do)

A draft nobody taps stays a draft and comes up in the evening review (WA-05),
so nothing is lost and nothing unchecked reaches the DPR.

The tap carries what it is about -- `agt:<action>:<code><uuid hex>.<...>` --
so no state is kept between the reply and the tap; the save-first service
checks each draft is the tapper's own, in their own company, and still a draft.
A reply that saved anything the review log does not cover (a progress update)
or more than `MAX_ITEMS` records keeps the old Undo button instead.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from channel.replies import ListRow, ReplySpec
from interactions.saved_summary import QUESTION_PREFIX, SAVED_HEADER
from runtime.reply_composer import UNDO_ROW, pick_form
from runtime.save_first import FACT_TYPE_BY_ACTION

from .cards import removed_line

#: WhatsApp reply-button ids hold 256 characters: "agt:cancel:" + 34 each.
MAX_ITEMS = 7
TAP_PREFIX = "agt:"
SAVE = "save"
CANCEL = "cancel"
#: Request 88: a row of the "which one should I remove?" list.
UNDO = "undo"

SAVE_TITLE = "✅ Save"
#: Request 104: the tap of a card that only sends the engineer a question.
SEND_TITLE = "✅ Send"
CANCEL_TITLE = "❌ Cancel"
#: Replaces "✅ Saved:" at the top of a reply whose records wait on the tap.
TO_SAVE_HEADER = "📝 To save:"

SAVED_DONE = "✅ Saved."
CANCELLED_DONE = "❌ Okay, nothing saved. Send it again whenever you're ready."
ALREADY_DONE = "That one is already done."
#: Request 90: entries were prepared that no Save card could show (more than
#: one tap holds): they are taken back, never left as unseen drafts.
NOT_SHOWN = (
    f"Nothing was kept: that was more than {MAX_ITEMS} entries, too many to check on one card. "
    "Please send it again in smaller parts."
)
EXPIRED = "That message has expired."
CANT_UNDO_ACTION = "That one has already been done, so it can't be taken back here."
REFUSED = "Couldn't {what} {n} of them: {why}."
#: A tap on one entry that can't be settled, said as a sentence (round 3,
#: 21 Oct: "Couldn't cancel 1 of them: it was already saved; fix it on the
#: dashboard." read as an error). Keyed by settle_drafts' reasons.
REFUSED_ONE = {
    "it was already saved; fix it on the dashboard": (
        "That one is already saved, so it can't be cancelled here. To change it, edit it on the dashboard."
    ),
    "it was already cancelled; send it again": (
        "That one was already cancelled. Send it again if you want to save it."
    ),
    "not your entry": "That's not your entry: only the person who sent it can save or cancel it.",
}

#: One letter per review fact type, to keep the tap id short.
_CODES: dict[str, str] = {
    "action": "x",  # request 104: a pending action (runtime/agent/actions.py), not a draft
    "activity": "a",
    "labour_report": "l",
    "material_receipt": "r",
    "material_usage": "u",
    "site_issue": "i",
}
_TYPES = {code: fact_type for fact_type, code in _CODES.items()}



def fact_of(handled: Any) -> tuple[str, uuid.UUID] | None:
    """(review fact type, record id) of one saved draft, or None when the
    review log does not cover it."""
    if not getattr(handled, "saved_draft", False):
        return None
    execution = getattr(handled, "execution_result", None)
    confirmed = getattr(getattr(handled, "result", None), "confirmed_action", None)
    row_id = getattr(execution, "material_row_id", None)
    if row_id is None or confirmed is None:
        return None
    fact_type = FACT_TYPE_BY_ACTION.get(confirmed.draft_action.action_type)
    try:
        fact_id = uuid.UUID(str(row_id))
    except ValueError:
        return None
    return (fact_type, fact_id) if fact_type is not None else None


def is_engineer_question(handled: Any) -> bool:
    """A question passed to the engineer (note_for_engineer): saved as an open
    issue so the engineer sees it, but no entry of the sender's to check."""
    confirmed = getattr(getattr(handled, "result", None), "confirmed_action", None)
    fields = getattr(getattr(confirmed, "draft_action", None), "fields", None) or {}
    return str(fields.get("narrative") or "").startswith(QUESTION_PREFIX)


def facts_of(
    handled_list: Iterable[Any],
    *,
    before: Iterable[tuple[str, uuid.UUID]] = (),
    after: Iterable[tuple[str, uuid.UUID]] = (),
) -> list[tuple[str, uuid.UUID]] | None:
    """Every entry the reply saved, when each is a reviewable draft and they
    fit one tap; None otherwise (the reply keeps its Undo button). Questions
    passed to the engineer are not entries and are left out (WA-37).
    ``before`` / ``after``: entries of an open card the reply shows again
    around the ones it saved (request 88)."""
    facts = list(before)
    for handled in handled_list:
        if is_engineer_question(handled):
            continue
        fact = fact_of(handled)
        if fact is None:
            return None
        facts.append(fact)
    facts.extend(after)
    return facts if 0 < len(facts) <= MAX_ITEMS else None


def entries_of(handled_list: Iterable[Any]) -> list[Any]:
    """The records a reply wrote that the sender must check: saved drafts,
    except a question passed on to the engineer."""
    return [h for h in handled_list if getattr(h, "saved_draft", False) and not is_engineer_question(h)]


def card_plan(
    handled_list: Iterable[Any],
    *,
    before: Iterable[tuple[str, uuid.UUID]] = (),
    after: Iterable[tuple[str, uuid.UUID]] = (),
) -> tuple[str, list[tuple[str, uuid.UUID]]]:
    """Request 90: what the reply must do about the records it wrote. One write
    path: a record is only ever prepared, and the sender sees it on a card.

    - ``"none"``: nothing to check;
    - ``"card"``: Save / Cancel under the reply (the facts the buttons carry);
    - ``"blocked"``: records were written but no card can hold them (more than
      one tap holds): the reply is held back and the facts are to be taken back;
    - ``"legacy"``: records the review log does not cover (a progress update)
      keep the old Undo button -- logged as an error, never silent."""
    handled = list(handled_list)
    entries = entries_of(handled)
    if not entries and not list(before) and not list(after):
        return "none", []
    facts = facts_of(handled, before=before, after=after)
    if facts is not None:
        return "card", facts
    own = [fact_of(h) for h in entries]
    if entries and all(f is not None for f in own):
        return "blocked", [f for f in own if f is not None]
    return "legacy", []


def tap_id(action: str, facts: list[tuple[str, uuid.UUID]]) -> str:
    return f"{TAP_PREFIX}{action}:" + ".".join(f"{_CODES[t]}{i.hex}" for t, i in facts)


def parse_tap(value: str) -> tuple[str, list[tuple[str, uuid.UUID]]] | None:
    """(action, facts) from a tap id; None when it is not ours or malformed."""
    if not value.startswith(TAP_PREFIX):
        return None
    action, _, body = value[len(TAP_PREFIX) :].partition(":")
    if action not in (SAVE, CANCEL, UNDO) or not body:
        return None
    facts = []
    for part in body.split("."):
        fact_type = _TYPES.get(part[:1])
        try:
            fact_id = uuid.UUID(hex=part[1:])
        except ValueError:
            return None
        if fact_type is None:
            return None
        facts.append((fact_type, fact_id))
    return (action, facts) if len(facts) <= MAX_ITEMS else None


def with_save_buttons(
    spec: ReplySpec,
    facts: list[tuple[str, uuid.UUID]],
    *,
    save_title: str = SAVE_TITLE,
    site: str | None = None,
) -> ReplySpec:
    """The composed reply with Save / Cancel in place of Undo, and its
    "Saved:" header saying the records still wait on the tap (naming the
    site when ``site`` is given). Any other
    choice it carried (the team-photo offer) stays after them."""
    # The system's line sits under the model's own words (WA-37), so the
    # header is the last one in the text, at the start of its line.
    before, found, after = spec.text.rpartition(SAVED_HEADER)
    text = spec.text
    if found and (not before or before.endswith("\n")):
        # SIT-11: a sender with several sites sees which one the entries are for.
        header = f"{TO_SAVE_HEADER[:-1]} · {site}:" if site else TO_SAVE_HEADER
        text = before + header + after
    others = [row for row in (spec.buttons or spec.list_rows or ()) if row.id != UNDO_ROW.id]
    rows = [
        ListRow(tap_id(SAVE, facts), save_title),
        ListRow(tap_id(CANCEL, facts), CANCEL_TITLE),
        *others,
    ][:3]
    return replace(pick_form(text, rows), header_image=spec.header_image)


def question_as_text(spec: ReplySpec) -> ReplySpec:
    """``spec`` without its buttons or list: the options are written under the
    question (bulleted, never numbered: a typed number would pick Save), so it can still
    be answered by typing. Used when the
    reply must carry the Save card instead (request 90)."""
    rows = list(spec.buttons or spec.list_rows or ())
    if not rows:
        return spec
    lines = "\n".join(f"• {row.title}" for row in rows)
    return replace(spec, text=f"{spec.text}\n\n{lines}", buttons=None, list_rows=None, list_button_label=None)


def tap_reply(action: str, settled: Any) -> str:
    """What the sender hears after tapping Save or Cancel."""
    lines = []
    if settled.done:
        lines.append(SAVED_DONE if action == SAVE else CANCELLED_DONE)
    elif not settled.refused:
        lines.append(ALREADY_DONE)
    if settled.refused and not settled.done and len(settled.refused) == 1 and settled.refused[0] in REFUSED_ONE:
        lines = [REFUSED_ONE[settled.refused[0]]]
    elif settled.refused:
        lines.append(
            REFUSED.format(
                what="save" if action == SAVE else "cancel",
                n=len(settled.refused),
                why=settled.refused[0],
            )
        )
    return "\n".join(lines)


async def handle_tap(
    message: Any,
    actor: Any,
    interaction_handler: Any,
    cards: Any | None = None,
    actions: Any | None = None,
    sender: Any | None = None,
) -> ReplySpec | None:
    """The reply to a Save / Cancel / remove tap, or None when the message is
    not one. ``cards`` (runtime/agent/cards.py) keeps the sender's latest card
    in step with the tap: Save marks it saved, Cancel and remove drop it.
    ``actions`` (runtime/agent/actions.py) runs the card's pending actions on
    Save (a question for the engineer, the day's weather, issues to close) and
    drops them on Cancel; ``sender`` is the WhatsApp sender they may use."""
    from .actions import ACTION_FACT, GONE_LINE

    tap = str((message.metadata or {}).get("interactive_reply_id") or "")
    if not tap.startswith(TAP_PREFIX):
        return None
    parsed = parse_tap(tap)
    if parsed is None:
        return ReplySpec(text=EXPIRED)
    action, facts = parsed
    org = str(actor.organization_id) if actor.organization_id else None
    if action == UNDO:
        return await _undo_tap(actor, interaction_handler, cards, org, facts, actions)
    drafts = [f for f in facts if f[0] != ACTION_FACT]
    pending = [f for f in facts if f[0] == ACTION_FACT]
    card = None
    if cards is not None:
        try:
            card = await cards.get(actor)
        except Exception:  # noqa: BLE001 -- the card only helps undo and edit
            card = None
    lines: list[str] = []
    settled = None
    if drafts:
        settled = await interaction_handler.settle_drafts(
            organization_id=org,
            user_id=actor.user_id,
            facts=drafts,
            keep=action == SAVE,
        )
        if settled is None:
            return ReplySpec(text=EXPIRED)
        lines.append(tap_reply(action, settled))
    ran = not drafts
    for _kind, action_id in pending:
        if actions is None:
            lines.append(GONE_LINE)
            continue
        if action == CANCEL:
            await actions.store.drop(actor, action_id.hex)
            continue
        waiting = await actions.store.take(actor, action_id.hex)
        lines.append(await actions.run(waiting, actor, sender) if waiting is not None else ALREADY_DONE)
        ran = True
    if pending and action == CANCEL and not drafts:
        lines.append(CANCELLED_DONE)
    if cards is not None and card is not None and (settled.done if settled is not None else ran):
        await cards.settle(actor, facts, keep=action == SAVE)
    return ReplySpec(text="\n".join(line for line in lines if line))


async def _undo_tap(
    actor: Any, interaction_handler: Any, cards: Any | None, org: str | None, facts: list, actions: Any | None = None
) -> ReplySpec:
    """A row of the remove list: exactly those entries, by their own undo. A
    pending action (not yet tapped) is simply dropped; one that ran cannot be
    taken back (a sent message stays sent)."""
    from .actions import ACTION_FACT
    from .journey_gateway import undo_step

    card = await cards.get(actor) if cards is not None else None
    pending = [f for f in facts if f[0] == ACTION_FACT]
    drafts = [f for f in facts if f[0] != ACTION_FACT]
    notes: list[str] = []
    dropped: list[Any] = []
    for fact in pending:
        if card is not None and card.state == "open" and actions is not None:
            await actions.store.drop(actor, fact[1].hex)
            dropped.append(fact)
        else:
            notes.append(CANT_UNDO_ACTION)
    undone = None
    if drafts:
        undo = getattr(interaction_handler, "undo_facts", None)
        undone = await undo(organization_id=org, user_id=actor.user_id, facts=drafts) if undo else None
        if undone is None:
            return ReplySpec(text=EXPIRED)
    done = [*(undone.done if undone is not None else []), *dropped]
    items = [i for i in (card.items if card else []) if i.fact in set(done)]
    if cards is not None and done:
        await cards.drop(actor, list(done))
    if items:
        text = undo_step(items, undone).text if undone is not None else removed_line(items)
        return ReplySpec(text="\n".join([text, *notes]))
    if done:
        return ReplySpec(text="\n".join(["Removed.", *notes]))
    if notes:
        return ReplySpec(text="\n".join(notes))
    return ReplySpec(text=undo_step([], undone).text)
