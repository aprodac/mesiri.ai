"""Request 185: the replay test's own tests (no model, no real data).

The checks are measured on the failure families seen live 27-31 Oct, each with the guard that
must NOT be flagged. The kit replays a made-up conversation through v2 with a scripted model.
"""

from __future__ import annotations

from tests.agent_v2.replaykit import V2Engine, replay

from agent_v2.replay import corpus as cp
from agent_v2.replay.checks import SEVERE, check_conversation
from agent_v2.replay.report import Scored, summary
from mesiri_ai.fakes import FakeToolCallingProvider


def names(texts, replies, kinds=None):
    return [(f.check, f.turn) for f in check_conversation(texts, replies, kinds)]


# ── checks: each family, and its guard ─────────────────────────────────────


def test_a_send_it_again_after_an_answer_is_a_dead_end_in_every_language():
    for reply in (
        "That wasn't saved or changed. Please send it again in one line: the work, the place and the figure.",
        "Athu save/maattan pattiyilla. Work, sthalam, figure ennivayode oru line-il veendum ayakku.",
        "അത് സേവ് ചെയ്യാനോ മാറ്റാനോ കഴിഞ്ഞില്ല. പണി, സ്ഥലം, കണക്ക് എന്നിവ ഒരു വരിയിൽ വീണ്ടും അയക്കുക.",
    ):
        assert ("dead_end", 0) in names(["50 bag = 1 load"], [reply])


def test_the_same_question_after_the_sender_answered_is_flagged_and_a_new_question_is_not():
    texts = ["issue close cheyyu", "Hospital Project"]
    assert ("repeated_question", 1) in names(texts, ["Which project is this for?", "Which project is this for?"])
    assert not names(texts, ["Which project is this for?", "Which issue should I close?"])


def test_the_same_reply_to_a_complaint_is_flagged_but_the_same_message_twice_is_not():
    dump = "📦 *Current inventory*\nCement — 226 bags"
    flagged = names(["cement stock?", "I never asked for inventory"], [dump, dump])
    assert ("repeated_reply", 1) in flagged and ("unasked_dump", 1) in flagged
    assert not names(["cement stock?", "cement stock?"], ["176 bags.", "176 bags."])


def test_saying_it_cannot_see_an_earlier_message_is_flagged():
    for reply in ("I can only see what you type to me.", "Sorry, njan aa pazhaya message kandilla."):
        assert ("cant_see", 0) in names(["Can't you see?"], [reply])


def test_a_stock_list_is_unasked_only_when_the_message_did_not_ask_about_stock():
    dump = "📦 *Current inventory*\nCement — 176 bags"
    assert ("unasked_dump", 0) in names(["Green Villa-il ethra open issues und?"], [dump])
    assert not names(["ethra stock und?"], [dump])
    assert not names(["innathe stock list tharu"], [dump])


def test_card_words_count_only_in_prose_not_on_the_card_lines():
    assert ("card_jargon", 0) in names(["x"], ["Card nokki shariyenkil Save tap cheyyu."])
    assert not names(["x"], ["Sheri.\n🟠 *To save* · Tower A: Cement in: 50 bags"])


def test_system_notices_are_counted_on_their_own_and_are_not_severe():
    limit = "You've reached today's free-trial limit, so I can't read more updates today."
    found = names(["help", "diesel 500"], [limit, limit])
    assert ("trial_limit", 0) in found and not any(c == "repeated_reply" for c, _ in found)
    assert "trial_limit" not in SEVERE and "outage" not in SEVERE and "card_jargon" not in SEVERE


def test_an_empty_reply_is_severe():
    assert ("no_reply", 0) in names(["hello"], [""])


def test_negative_stock_is_flagged():
    assert ("negative_stock", 0) in names(["stock?"], ["Fevicol −2 pieces"])


# ── corpus ─────────────────────────────────────────────────────────────────


def _row(at, text, reply="ok", s="1234", t="text"):
    return {"received_at": at, "org": "Acme", "s": s, "t": t, "body": text, "reply": reply, "correlation_id": at}


def test_a_long_gap_or_another_sender_starts_a_new_conversation(tmp_path):
    rows = [
        _row("2026-10-31T07:00:00+00:00", "a"),
        _row("2026-10-31T07:10:00+00:00", "b"),
        _row("2026-10-31T09:00:00+00:00", "c"),
        _row("2026-10-31T07:05:00+00:00", "x", s="9999"),
        _row("2026-10-31T07:06:00+00:00", '{"text": null, "media": {}}', t="voice"),
    ]
    convs = cp.group(rows)
    assert [[t.text for t in c.turns] for c in convs] == [["a", "", "b"], ["x"], ["c"]]
    assert not convs[0].turns[1].replayable  # a voice note with no transcript
    path = cp.save(convs, tmp_path / "c.jsonl")
    assert [c.key for c in cp.load(path)] == [c.key for c in convs]


def test_the_summary_counts_clean_conversations():
    scored = [Scored("a", 2, []), Scored("b", 3, check_conversation(["x"], [""]))]
    text = summary("t", scored)
    assert "clean conversations: 1/2" in text and "turns: 5" in text


# ── the kit, end to end on a scripted model ────────────────────────────────


async def test_a_conversation_replays_through_v2_and_a_save_tap_presses_the_card_button():
    conv = cp.Conversation(
        company="Acme",
        sender="1234",
        turns=[
            cp.Turn("c1", "2026-10-31T07:00:00+00:00", cp.TEXT, "50 bag cement vannu"),
            cp.Turn("c2", "2026-10-31T07:01:00+00:00", cp.TAP, "✅ Save"),
            cp.Turn("c3", "2026-10-31T07:02:00+00:00", cp.VOICE, "cement ethra und?"),
        ],
    )
    provider = FakeToolCallingProvider(
        [
            [("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})],
            "Sheri, 50 bag cement vannu.",
            [("stock_for", {"material": "cement"})],
            "Cement 226 bags und.",
        ]
    )
    out = await replay(conv, V2Engine(provider))
    assert not out.errors, out.errors
    assert len(out.replies) == 3 and all(out.replies)
    assert "Saved" in out.replies[1]  # the tap went to the card's Save button, not the model
    assert out.kinds == [cp.TEXT, cp.TAP, cp.VOICE]


def test_the_newest_day_is_held_out_and_the_splits_do_not_overlap():
    convs = cp.group(
        [_row("2026-10-29T07:00:00+00:00", "a"), _row("2026-10-30T07:00:00+00:00", "b"), _row("2026-10-31T07:00:00+00:00", "c")]
    )
    tune, held = cp.split(convs, "tune"), cp.split(convs, "holdout")
    assert [c.turns[0].text for c in held] == ["c"]
    assert [c.turns[0].text for c in tune] == ["a", "b"]
    assert len(cp.split(convs, "all")) == 3
