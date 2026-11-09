"""PRC-34: GST on a delivery and an order is said on WhatsApp the way it is on the dashboard.

The model sees ``gst_percent`` and ``rate_includes_gst`` on the real API's delivery and order tools (the SOP
says when to fill them: only when said or printed). Guard: the fields the model must not see stay hidden.
(A bill on WhatsApp is an expense, whose GST is ``tax_amount`` already.)
"""

from __future__ import annotations

from tests.agent_api.replaykit import _real_tools


def test_delivery_and_order_tools_take_gst_on_the_real_api() -> None:
    tools = _real_tools()
    for name in ("record_receipt", "place_order"):
        fields = tools[name].body_fields
        assert "gst_percent" in fields and "rate_includes_gst" in fields, name
    assert "vendor_id" not in tools["record_receipt"].body_fields
    assert "lines" not in tools["place_order"].body_fields


def test_the_sop_says_gst_only_when_said() -> None:
    from pathlib import Path

    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "`gst_percent` only when they said it" in sop and "never ask only for GST" in sop
