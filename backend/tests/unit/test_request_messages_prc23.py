"""PRC-23: what the person who asked for material is told, in their reply language (none chosen: Manglish)."""

from mesiri.domains.procurement.requests import requester_message

ITEM = {"ref": "REQ-0004", "lines": [{"quantity": "160", "unit": "bags", "material": "Cement"}]}


def test_each_language_and_the_default() -> None:
    assert requester_message(ITEM, "ordered", "PO-0003, Malabar", "Meera", "english") == \
        "🛒 Ordered by Meera: 160 bags Cement (PO-0003, Malabar). REQ-0004"
    assert requester_message(ITEM, "ordered", None, "Meera", None) == "🛒 Order cheythu (Meera): 160 bags Cement. REQ-0004"
    assert requester_message(ITEM, "waiting", "PO-0003 cancelled: price", None, "malayalam").startswith("↩️ ഇപ്പോൾ വരില്ല")
    assert requester_message(ITEM, "rejected", "enough at site", "Meera", "hindi").startswith("✖️ Not ordered by Meera")


def test_received_by_its_orders_is_not_marked_by_hand() -> None:
    assert requester_message(ITEM, "received", None, "Meera", "english") == "✅ Received: 160 bags Cement. REQ-0004"
    assert requester_message(ITEM, "done", None, "Meera", "english").startswith("✅ Marked received by Meera")


def test_every_status_has_all_three_languages() -> None:
    for status in ("ordered", "sent", "rejected", "done", "received", "waiting"):
        for language in ("english", "manglish", "malayalam"):
            assert requester_message(ITEM, status, "x", "Meera", language)
