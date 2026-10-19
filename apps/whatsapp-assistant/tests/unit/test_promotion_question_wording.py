"""The worker-promotion question says why, about whom, with buttons, in the
sender's language (request [51])."""

from __future__ import annotations

from channel.replies import ListRow, ReplySpec
from runtime.reply_composer import QUESTION, Offer, compose
from runtime.reply_language import localize_reply_spec
from workflows.worker_promotion import wording
from workflows.worker_promotion.nodes import PROMOTION_SLOT, offer_and_promote


def _offer_state(names):
    return {
        "workflow_instance_id": "wf",
        "workflow_key": "labour.worker_promotion",
        "correlation_id": "c",
        "organization_id": "o",
        "user_id": "u",
        "collected_fields": {"promotable_workers": [{"name": n, "trade": "mason"} for n in names]},
    }


def test_a_sentence_that_merely_mentions_a_name_is_not_a_pick():
    state = _offer_state(["Anil", "Suresh"])
    state["awaiting_slot"] = PROMOTION_SLOT
    state["collected_fields"]["_slot_answer_text"] = "I have work on Anil site today"

    result = offer_and_promote(state)

    assert result["pending_prompt"].startswith("No worries.")
    assert not result["collected_fields"].get("workers_to_create")


def test_the_promotion_question_arrives_inside_the_one_reply_with_its_buttons():
    offer = offer_and_promote(_offer_state(["Anil", "Suresh"]))
    spec = ReplySpec(
        text=offer["pending_prompt"],
        buttons=tuple(ListRow(o["value"], o["label"]) for o in offer["awaiting_slot_options"]),
    )

    reply = compose("✅ Saved: 2 workers today", [Offer(QUESTION, spec=spec)], saved=True)

    assert reply.text.startswith("✅ Saved: 2 workers today\n\nQuick check so your worker list")
    assert [b.title for b in reply.buttons] == ["Add both", "Choose", "Not now"]
    assert [b.id for b in reply.buttons] == ["promo_all", "promo_choose", "promo_none"]


def test_a_plain_text_question_is_still_plain_text():
    reply = compose("Saved", [Offer(QUESTION, text="Which site?")])

    assert reply.text == "Saved\n\nWhich site?"
    assert not reply.buttons


def test_malayalam_keeps_names_and_translates_the_sentences_and_buttons():
    offer = offer_and_promote(_offer_state(["Anil", "Suresh"]))
    spec = ReplySpec(
        text=offer["pending_prompt"],
        buttons=tuple(ListRow(o["value"], o["label"]) for o in offer["awaiting_slot_options"]),
    )

    out = localize_reply_spec(spec, "ml")

    assert "*Anil* and *Suresh*" in out.text
    assert "Quick check" not in out.text and "permanent" not in out.text
    assert [b.id for b in out.buttons] == ["promo_all", "promo_choose", "promo_none"]
    assert all(b.title != e for b, e in zip(out.buttons, spec.buttons, strict=True))
    assert all(len(b.title) <= 20 for b in out.buttons)


def test_the_look_alike_question_is_translated_with_the_register_name_intact():
    text = f"{wording.INTRO}\n\n" + wording.LOOKS_LIKE.format(
        new="*Rajesh*", old="*Rajesh Kumar*", detail=" (mason, since 2 Oct)"
    )

    out = localize_reply_spec(ReplySpec(text=text), "hindi").text

    assert "*Rajesh*" in out and "*Rajesh Kumar*" in out and "(mason, since 2 Oct)" in out
    assert "looks like" not in out


def test_english_and_unknown_languages_are_left_alone():
    spec = ReplySpec(text=wording.INTRO, buttons=(ListRow("dup_skip", "Skip"),))

    assert localize_reply_spec(spec, "en") is spec
    assert localize_reply_spec(spec, None) is spec
    assert localize_reply_spec(spec, "tamil") is spec


def test_every_template_has_a_translation_in_each_language():
    from runtime.reply_language import _BUTTON_TITLES, _PROMOTION_TEMPLATES

    for language, table in _PROMOTION_TEMPLATES.items():
        assert set(table) == set(wording.TEMPLATES), language
        assert set(_BUTTON_TITLES[language]) == set(wording.BUTTON_TITLES), language
