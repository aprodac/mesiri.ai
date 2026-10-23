"""Request 94: the kinder Cancel line in each language, the DPR caption language,
and the labour answer carrying every trade with its number."""

from __future__ import annotations

from channel.replies import ReplySpec
from runtime.agent import save_button
from runtime.agent.query_entry import _one_name_per_trade
from runtime.agent.reply_text import dpr_caption
from runtime.reply_language import localize_fixed_reply, localize_reply_spec
from workflows.labour_query.nodes import generate_labour_query_reply


def test_cancel_line_english_is_not_blaming():
    assert save_button.CANCELLED_DONE == "❌ Okay, nothing saved. Send it again whenever you're ready."
    assert "right way" not in save_button.CANCELLED_DONE


def test_cancel_line_manglish():
    said = localize_fixed_reply(save_button.CANCELLED_DONE, "Malayalam", "latin")
    assert said == "❌ Sheri, onnum save cheythilla. Ready aakumbol veendum ayakku."
    spec = localize_reply_spec(ReplySpec(text=save_button.CANCELLED_DONE), "ml", "latin")
    assert spec.text == said


def test_cancel_line_malayalam_script():
    said = localize_fixed_reply(save_button.CANCELLED_DONE, "Malayalam", "native")
    assert said.startswith("❌ ശരി, ഒന്നും സേവ് ചെയ്തിട്ടില്ല")


def test_cancel_line_english_sender_unchanged():
    assert localize_fixed_reply(save_button.CANCELLED_DONE, None, "latin") == save_button.CANCELLED_DONE


def test_manglish_swap_leaves_other_text_alone():
    text = "✅ Saved.\nCouldn't cancel 1 of them: x."
    assert localize_fixed_reply(text, "Malayalam", "latin") == text


def test_dpr_caption_follows_the_reply_language():
    answer = "The DPR for 22 Oct 2026 (DPR-1) attached."
    assert dpr_caption(answer, "manglish") == "22 Oct 2026-inte DPR (DPR-1) ithaa."
    assert dpr_caption("Today's DPR (D-1) attached. Not confirmed yet.", "manglish") == (
        "Innathe DPR (D-1) ithaa. Confirm cheythittilla."
    )
    assert dpr_caption(answer, "malayalam") == "22 Oct 2026-ലെ DPR (DPR-1) ഇതാ."
    assert dpr_caption(answer, "english") is None
    assert dpr_caption("No DPR has been generated for today yet.", "manglish") is None


def test_a_second_save_of_the_same_trade_keeps_every_trade_with_numbers():
    rows = [
        {"trade": "mason", "headcount": 1},
        {"trade": "masons", "headcount": 3},
        {"trade": "painter", "headcount": 2},
    ]
    results = {"headcount": 6, "total_cost": "0", "trades": ["mason", "masons", "painter"], "rows": rows,
               "named": [], "days": 1, "date_range_label": "today"}
    _one_name_per_trade(results)
    assert results["trade_counts"] == [["mason", 4], ["painter", 2]]
    reply = generate_labour_query_reply({"collected_fields": {"labour_results": results}})["pending_prompt"]
    assert "6 workers" in reply
    assert "By trade: 4 Mason, 2 Painter" in reply


def test_trade_counts_absent_without_lines_keeps_the_old_trades_line():
    results = {"headcount": 2, "trades": ["mason"], "days": 1}
    _one_name_per_trade(results)
    assert "trade_counts" not in results
    reply = generate_labour_query_reply({"collected_fields": {"labour_results": results}})["pending_prompt"]
    assert "Trades: Mason" in reply
