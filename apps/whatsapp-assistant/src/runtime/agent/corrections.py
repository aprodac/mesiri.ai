"""Words that TAKE SOMETHING AWAY, read by code before the model (request 162).

Live 31 Oct: a card carried "10 workers" that Adarsh never said. He cancelled it and
said "I didn't say anything about workers"; with no code path for a removal the
model read the sentence as a material name and asked "what is this material's
correct name?". This module is that path, one for every kind of line:

- the open card: the named kind (or named material) is taken off it and the card is
  shown again;
- right after Cancel there is no card, so the cancelled one is rebuilt without it
  and shown with Save (nothing is saved without the tap);
- right after Save the record exists, so it is the undo flow's confirm card
  (``undo_flow.request``), never a silent delete.

It also holds the staging guard: a line may only be staged from words that could
have said it. And the stale tap: an old button whose card is gone never acts as a
fresh answer; it is said, in the sender's language, with the card that is open.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from channel.replies import ReplySpec

from . import draft as dr
from .wording import say

_log = logging.getLogger("mesiri.agent")

#: How long after Cancel / Save a removal word still means that card.
CLOSED_WINDOW_SECONDS = 30 * 60

#: "not / didn't say / venda / remove / ozhivaakku": the words that take a thing away.
#: Plain "not" or "no" are NOT here: "cement not received" is a statement, and
#: "alla, 6 mason aanu" is a correction of a count (it has no removal word).
_REMOVE = re.compile(
    r"didn'?t (?:say|mention|tell|send)|did not (?:say|mention|tell|send)|never (?:said|mentioned|told)|"
    r"not (?:said|mentioned)|no mention|i never|"
    r"(?<![\w])venda+(?![\w])|വേണ്ട|remove|delete|take (?:it |them )?(?:off|out)|get rid|"
    r"ozhiv\w+|ഒഴിവാക്ക\w*|ഒഴിവാക്കൂ|hata\w*|हटा\w*|nahi chahiye|नहीं चाहिए|"
    r"paranjitt?illa|paranjilla|പറഞ്ഞില്ല|പറഞ്ഞിട്ടില്ല|bola nahi|nahi bola|नहीं बोला|"
    r"(?<![\w])without(?![\w])",
    re.IGNORECASE,
)
#: A clause ends at punctuation or "and": "only M sand and P sand, I didn't say workers".
_CLAUSE = re.compile(r"[,.;!?\n]|(?<![\w])and(?![\w])|(?<![\w])pinne(?![\w])", re.IGNORECASE)

_LABOUR = re.compile(
    r"(?<![\w])(?:workers?|labou?rs?|labou?rers?|manpower|aal(?:ukal)?|aalukal|thozhilali\w*|mazdoor\w*|mistri\w*)(?![\w])"
    r"|തൊഴിലാളി\w*|ആളുകൾ|ആൾക്കാർ|मजदूर|मजदूरों|कारीगर",
    re.IGNORECASE,
)
_EXPENSE = re.compile(
    r"(?<![\w])(?:expenses?|kharcha|kharch|chilav|cost|spending|bill)(?![\w])|ചെലവ്|ചിലവ്|खर्च|खर्चा",
    re.IGNORECASE,
)
_ISSUE = re.compile(r"(?<![\w])(?:issues?|problems?|complaints?|prashnam)(?![\w])|പ്രശ്നം|समस्या", re.IGNORECASE)
_MATERIAL = re.compile(r"(?<![\w])(?:materials?|saadhanam|samagri)(?![\w])|സാധനം|सामग्री", re.IGNORECASE)

_KINDS: dict[str, tuple[re.Pattern[str], tuple[str, ...], str]] = {
    "labour": (_LABOUR, (dr.KIND_LABOUR,), "labour"),
    "expense": (_EXPENSE, (dr.KIND_EXPENSE,), "expense"),
    "issue": (_ISSUE, (dr.KIND_ISSUE_OPEN, dr.KIND_ISSUE_STATUS), "issue"),
    "material": (
        _MATERIAL,
        (dr.KIND_MATERIAL_IN, dr.KIND_MATERIAL_OUT, dr.KIND_TRANSFER_MATERIAL, dr.KIND_OPENING_STOCK, dr.KIND_STOCK_COUNT),
        "material",
    ),
}
_MATERIAL_KINDS = _KINDS["material"][1]


def _removal_clauses(text: str) -> list[str]:
    """The clauses of ``text`` that carry a removal word."""
    return [c for c in _CLAUSE.split(text or "") if c and _REMOVE.search(c)]


def removal_kinds(text: str) -> list[str]:
    """Which kinds of line the words take away: ``["labour"]`` for "I didn't say
    anything about workers" / "workers venda". Empty when they take nothing away
    (a count correction, a plain statement)."""
    clauses = _removal_clauses(text)
    return [kind for kind, (pattern, _tools, _ref) in _KINDS.items() if any(pattern.search(c) for c in clauses)]


def _named_material(item: dr.DraftItem) -> str:
    return " ".join(str(item.args.get("material") or "").split()).casefold()


def items_removed(items: list[dr.DraftItem], text: str) -> list[dr.DraftItem]:
    """The items of a card the words take away: every item of a named kind, and a
    material line whose material is named in the same clause as the removal word."""
    clauses = [c.casefold() for c in _removal_clauses(text)]
    if not clauses:
        return []
    kinds = removal_kinds(text)
    tools = {k for kind in kinds for k in _KINDS[kind][1]}
    out: list[dr.DraftItem] = []
    for item in items:
        if item.state == dr.UNREADABLE and not item.kind:
            continue
        named = _named_material(item)
        by_name = bool(named) and item.kind in _MATERIAL_KINDS and any(named in c for c in clauses)
        if item.kind in tools or by_name:
            out.append(item)
    return out


def ref_for(text: str) -> str:
    """The word the journal matches a saved record by ("labour", "expense", a
    material's name): the first kind the words take away."""
    kinds = removal_kinds(text)
    return _KINDS[kinds[0]][2] if kinds else ""


def _lines(items: list[dr.DraftItem]) -> str:
    return "; ".join(i.line for i in items if i.line) or "that"


async def correct(gw: Any, text: str) -> ReplySpec | None:
    """The reply to words that take something away, or None (the model reads the
    message): on the open card, on the card just cancelled, or on the one just saved."""
    if gw.actor is None or gw.drafts is None or not _removal_clauses(text):
        return None
    from . import draft_flow

    language = getattr(gw, "wording_language", "english")
    draft = await draft_flow.load(gw)
    if draft is not None and draft.live:
        gone = items_removed(draft.items, text)
        if not gone:
            return None
        return await _from_open_card(gw, draft, gone, language)
    org, user = draft_flow._owner(gw)
    closed = await gw.drafts.latest_closed(org, user, CLOSED_WINDOW_SECONDS)
    if closed is None:
        return None
    if closed.status == dr.DISCARDED:
        gone = items_removed(closed.items, text)
        return await _rebuild_without(gw, closed, gone, language) if gone else None
    # Saved: the record exists, so taking it back is the undo flow, asked first.
    if closed.status == dr.SAVED and getattr(gw, "journal_mode", False) is True and items_removed(closed.items, text):
        step = await gw.change_or_undo(ref_for(text))
        return step.reply or ReplySpec(text=step.text)
    return None


async def drop_from_open_card(gw: Any, draft: dr.MessageDraft, gone: list[dr.DraftItem]) -> bool:
    """Take ``gone`` off the open card, in place; the one place that does it (the typed
    removal here and the v2 agent's remove_card_line). True while lines remain; False when
    the card is empty and was discarded."""
    from . import draft_flow

    draft.items = [i for i in draft.items if i not in gone]
    if gw.actions is not None:
        for item in gone:
            if item.kind == dr.KIND_ACTION and item.action_id:
                await gw.actions.store.drop(gw.actor, item.action_id)
    _log.info("draft.removed draft=%s removed=%s left=%s", draft.id, len(gone), len(draft.items))
    if not draft.live:
        await gw.drafts.discard(draft.id)
        gw.draft = None
        return False
    await draft_flow._persist(gw, draft)
    draft_flow._keep(gw, draft)
    return True


async def _from_open_card(gw: Any, draft: dr.MessageDraft, gone: list[dr.DraftItem], language: str) -> ReplySpec:
    from . import draft_flow

    line = _lines(gone)
    if not await drop_from_open_card(gw, draft, gone):
        return ReplySpec(text=say("remove.empty", language, line=line))
    return dr.card_reply(draft, say("remove.done", language, line=line), site=draft_flow._card_site(gw, draft))


async def _rebuild_without(
    gw: Any, closed: dr.MessageDraft, gone: list[dr.DraftItem], language: str
) -> ReplySpec:
    """The card that was cancelled, again, without what they never said. The items
    keep their ids, so a tap on an old button of that card still finds its line."""
    from . import draft_flow

    kept = [i for i in closed.items if i not in gone and i.kind != dr.KIND_ACTION]
    line = _lines(gone)
    fresh = dr.MessageDraft.new(
        organization_id=closed.organization_id, user_id=closed.user_id, source_message_id=closed.source_message_id
    )
    fresh.items, fresh.project_id, fresh.site_id = kept, closed.project_id, closed.site_id
    if not fresh.live:
        return ReplySpec(text=say("remove.empty", language, line=line))
    await draft_flow._persist(gw, fresh)
    draft_flow._keep(gw, fresh)
    _log.info("draft.rebuilt from=%s removed=%s kept=%s", closed.id, len(gone), len(kept))
    return dr.card_reply(fresh, say("remove.rebuilt", language, line=line), site=draft_flow._card_site(gw, fresh))


# -- an old button: a card that is gone never acts as a fresh answer -----------------


async def current_card_reply(gw: Any, language: str) -> ReplySpec:
    """"That card was cancelled. Here's what I have now:" with the open card, or
    the plain line when nothing is open. The code's words, in their language."""
    from . import draft_flow

    draft = await draft_flow.load(gw)
    if draft is not None and draft.live:
        return dr.card_reply(draft, say("tap.old_card", language), site=draft_flow._card_site(gw, draft))
    return ReplySpec(text=say("tap.nothing_open", language))


async def old_card_tap(gw: Any, old: dr.MessageDraft, action: str, extra: tuple[str, ...]) -> ReplySpec:
    """A tap on a button of a cancelled or replaced card. Save never saves it. An
    answer is applied to the same line of the card that is open now, when there is
    one; otherwise the current card is shown. Never a question asked again."""
    from . import draft_flow

    language = getattr(gw, "wording_language", "english")
    current = await draft_flow.load(gw)
    if action == dr.ANSWER and current is not None and current.live and len(extra) == 2:
        item_id = extra[0]
        mine, there = current.item(item_id), old.item(item_id)
        if mine is not None and there is not None and mine.state == dr.NEEDS_ANSWER and mine.options == there.options:
            return await draft_flow.answer(gw, current, item_id, int(extra[1]))
    return await current_card_reply(gw, language)


def is_stale_option_tap(tap_id: str, title: str, last_reply: str | None) -> bool:
    """A tap on an ``agent_opt_N`` button (the model's question) whose question is
    no longer the last thing said: the last reply offered options and this is not one of them."""
    if not tap_id.startswith("agent_opt_"):
        return False
    title = " ".join((title or "").split()).casefold()
    if not title:
        return False
    reply = last_reply or ""
    if "\n[options:" not in reply:
        # Nothing is known of what was offered (the reply may have been recorded
        # without its buttons): the model reads the tap as before, never a guess.
        return False
    options = reply.rsplit("\n[options:", 1)[1].rstrip("] \n").split(" / ")
    shown = [" ".join(o.split()).casefold() for o in options]
    return not any(title == o or o.startswith(title.rstrip("…. ")) or title.startswith(o) for o in shown if o)


# -- the staging guard ------------------------------------------------------------------

_TRADES = re.compile(
    r"mason\w*|helper\w*|carpenter\w*|electrician\w*|plumber\w*|painter\w*|bar ?bender\w*|welder\w*|fitter\w*|"
    r"tile\w*|shuttering|mestri|mistri|cooli|coolie|mesthri|മേസൺ|മേസ്തിരി|ഹെൽപ്പർ|പണിക്കാർ|ആശാരി|आदमी|मिस्त्री|हेल्पर",
    re.IGNORECASE,
)
#: People and attendance, by themselves ("6 per vannu", "aaj 8 log aaye"). A bare figure is
#: NOT a cue: "50 bag cement vannu" has one and says nothing about workers.
_PEOPLE = re.compile(
    r"(?<![\w])(?:people|persons?|members?|log|per|aalu|aal|attend\w*|present|hajar\w*|worked|working|joined|"
    r"strength|headcount|crew|gang|team)(?![\w])|പേർ|ആൾ|ആളുകൾ|लोग|हाजिर",
    re.IGNORECASE,
)


def labour_was_said(text: str, *, answering: bool = False) -> bool:
    """The words could have said a labour count: a trade, a worker word or people/attendance. ``answering``: the call answers a question about a labour line on the
    card (its site), so its words are an answer, not a count."""
    if answering:
        return True
    text = text or ""
    return bool(_TRADES.search(text) or _LABOUR.search(text) or _PEOPLE.search(text))


#: The cue each kind of line needs in the current message. A kind not listed has no
#: guard yet (said in the request 162 report, not hidden).
STAGING_CUES = {dr.KIND_LABOUR: labour_was_said}


def staging_refused(
    kind: str, text: str, *, answering: bool = False, tap: bool = False, card_open: bool = True
) -> bool:
    """True when an item of ``kind`` may NOT be staged from ``text``: the message is a tap
    or a one-word answer ("M sand", "Received", "Green Villa") that carries none of
    the cue, so it cannot have said the item and an older message or draft is not a source.
    A longer message is not judged: words are too varied (voice, Manglish) to refuse a
    sentence on a missing cue, and a wrong refusal loses what the sender said."""
    cue = STAGING_CUES.get(kind)
    if cue is None or not (text or "").strip():
        return False
    short = tap or (card_open and len(text.split()) <= 1)
    return short and not cue(text, answering=answering)
