"""Request 174 (Phase B): the side-by-side report."""

from agent_v2.report import agree, side_by_side

SAME = {
    "message": "50 bag cement vannu",
    "v2": {"took_message": True, "handed_back": None, "calls": [
        {"tool": "draft_receipt", "args": {"material": "cement", "quantity": 50, "unit": "bags"}}], "ms": 1800},
    "classic": {"calls": [{"tool": "save_material_receipt", "args": {"material": "Cement", "quantity": 50}}]},
}
SPLIT = {
    "message": "സിമൻറ് 10 ചാക്ക് ഉപയോഗിച്ചു",
    "v2": {"took_message": True, "handed_back": None, "calls": [
        {"tool": "draft_usage", "args": {"material": "cement", "quantity": 10}}], "ms": 2000},
    "classic": {"calls": [{"tool": "save_material_usage", "args": {"material": "സിമൻറ്", "quantity": 10}}]},
}
LEFT = {"message": "6 mason", "v2": {"took_message": False, "handed_back": "labour", "calls": [], "ms": 900},
        "classic": {"calls": [{"tool": "save_labour", "args": {}}]}}


def test_same_lines_agree_and_split_names_do_not():
    assert agree(SAME) is True
    assert agree(SPLIT) is False
    assert agree(LEFT) is None


def test_the_report_has_a_block_per_message_and_totals():
    text = side_by_side([{"created_at": "t1", "stage_payload": p} for p in (SAME, SPLIT, LEFT)])
    assert "-> SAME" in text and "-> DIFFERENT" in text and "-> v2 left it" in text
    assert "hand back (labour)" in text
    assert "3 messages; v2 took 2; same as today's on 1" in text
