"""Request [63]: one reply per site update -- a plan step's reply is folded
into the saved reply. (The splitter's stray-query guard went with the classic
pipeline, ARCH-06: the agent never adds a query the sender didn't ask.)"""

from __future__ import annotations

from tests.unit.test_worker_promotion_wiring import _block_after, _dependencies_source


def test_save_first_folds_the_plan_reply_into_the_saved_reply():
    block = _block_after(_dependencies_source(), "async def _deliver_handled(", "def _succeeded(")
    assert "fold_plan_reply" in block
    assert "reply_text = f\"{reply_text}" in block
