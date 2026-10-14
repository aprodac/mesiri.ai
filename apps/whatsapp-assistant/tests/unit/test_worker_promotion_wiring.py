"""Worker promotion is hooked onto the paths that actually carry the events.

The bug these guard against shipped twice and was invisible to every other
test in the suite: the promotion functions were correct, fully unit-tested,
and called from the wrong place. Nothing ever triggered.

A confirmation reply ("yes", or a Confirm tap) is resolved by
``handle_fast_path`` in runtime/message_journey.py (split out of
runtime/dependencies.py, 2026-07-29), which sends its reply and **returns**
-- ``process_inbound_message`` (runtime/inbound_journey.py) never runs for
that message. The answer to the promotion offer arrives on the same file's
``handle_slot_answer`` branch, which also returns. Hooks placed in
inbound_journey therefore fire for nobody, which is exactly what happened.

These are source-level assertions rather than behavioural ones on purpose.
The failure mode is not "the function is wrong" -- it is "the function is
never reached", which a test that calls the function directly can never
detect. Checking the call site is the only thing that catches it.
"""

from __future__ import annotations

import inspect
import re


def _dependencies_source() -> str:
    import runtime.message_journey as journey

    return inspect.getsource(journey)


def _block_after(source: str, marker: str, stop: str) -> str:
    """The source between ``marker`` and the next occurrence of ``stop``."""
    start = source.index(marker)
    end = source.index(stop, start)
    return source[start:end]


def _confirmation_block(source: str) -> str:
    """The follow-ups a confirmed item gets. Since WA-01 they live in
    message_journey's `_deliver_handled`, shared by a typed "YES" (the fast
    path) and by save-first, so the fast path must hand over to it and the
    hooks must sit inside it."""
    fast_path = _block_after(
        source, "handle_fast_path(ctx.user_id, message, actor=ctx)", "handle_slot_answer"
    )
    assert "await _deliver_handled(handled)" in fast_path
    return _block_after(source, "async def _deliver_handled(", "async def _save_first_now(")


def test_save_first_gets_the_same_follow_ups_as_a_typed_yes():
    """WA-01: attendance saved without asking must still get the promotion
    and team-photo offers -- so save-first must deliver through the same
    `_deliver_handled`, not a copy."""
    block = _block_after(
        _dependencies_source(), "async def _save_first_now(", "async def _save_first_after_journey("
    )
    assert "await _deliver_handled(saved)" in block


def test_the_confirmation_fast_path_triggers_the_promotion_offer():
    """Attendance is confirmed here, so the follow-up offer has to be here."""
    source = _dependencies_source()
    block = _confirmation_block(source)
    # The *call*, not the import line -- an import alone proves nothing, and
    # matching the bare name let a first version of this test pass against a
    # hook that had been removed.
    assert "await _maybe_trigger_worker_promotion(" in block


def test_the_slot_answer_path_writes_the_promoted_workers():
    """The reply naming who to add arrives here, and the node cannot write."""
    source = _dependencies_source()
    block = _block_after(
        source,
        "handle_slot_answer(ctx.user_id, message)",
        "try_handle_account_admin_command",
    )
    assert "await _create_promoted_workers(" in block


def test_the_inbound_journey_does_not_pretend_to_handle_promotion():
    """Both hooks lived here once and fired for nobody. If they come back,
    it means someone re-made the same mistake -- the journey is not reached
    for either event."""
    import runtime.inbound_journey as journey

    source = inspect.getsource(journey)
    # The definitions still live here; only the *call sites* must not.
    calls = re.findall(
        r"^\s+(?:await\s+)?_safe\(\s*$\n\s+(_maybe_trigger_worker_promotion|_create_promoted_workers)\(",
        source,
        re.MULTILINE,
    )
    assert calls == [], f"promotion hooked into a path that never runs for it: {calls}"


# ---------------------------------------------------------------------------
# Team photo (Phase 4) is on the paths that carry its events
# ---------------------------------------------------------------------------


def test_the_team_photo_offer_follows_a_recorded_attendance():
    """Fires from the confirmation fast path when nothing is being promoted,
    so a report with no new names still gets the offer."""
    block = _confirmation_block(_dependencies_source())
    assert "await _offer_team_photo(" in block


def test_the_team_photo_offer_also_follows_the_promotion_answer():
    """The other entry point: when workers *were* promoted, the offer waits
    for that answer rather than arriving beside it."""
    block = _block_after(
        _dependencies_source(),
        "handle_slot_answer(ctx.user_id, message)",
        "try_handle_account_admin_command",
    )
    assert "await _offer_team_photo(" in block


def test_an_arriving_photo_is_checked_against_the_team_photo_hint():
    """Checked before the "what is this photo for?" picker: asking that about
    a photo sent in answer to Mesiri's own question is absurd, and the hint
    is pop-once so it must not be stepped past."""
    source = _dependencies_source()
    hint_at = source.index("_safe_pop_pending_report(\n                team_photo_hint_store")
    picker_at = source.index("try_hold_new_image_for_purpose_picker(")

    assert hint_at < picker_at, "the team-photo hint must be read before the picker"


def test_the_skip_tap_is_handled_before_the_confirmation_classifier():
    """"Skip" must never reach the confirmation classifier, which would read
    it as rejecting the attendance that was just recorded."""
    source = _dependencies_source()
    skip_at = source.index('team_photo_tap in ("team_photo_upload", "team_photo_skip")')
    fast_path_at = source.index("handle_fast_path(ctx.user_id, message, actor=ctx)")

    assert skip_at < fast_path_at


def test_the_report_id_is_parked_before_the_offer_is_deferred():
    """The bug this catches, which shipped once: when a report has new named
    workers the team-photo offer waits for the promotion answer, and the
    deferred branch pops a hint to learn which day the photo belongs to.

    An earlier version wrote that hint only inside _offer_team_photo -- which
    the deferred path does not reach -- so it popped an id nobody had
    written and the prompt never arrived, for exactly the reports most likely
    to want a photo. Both halves are asserted together because either alone
    looks correct.
    """
    block = _confirmation_block(_dependencies_source())
    park_at = block.index("_park_team_photo_report(")
    offer_at = block.index("await _offer_team_photo(")

    assert park_at < offer_at, "the report id must be parked before the offer branch"
    # ...and parked unconditionally, not only on the immediate path.
    assert "if report_id and not promotion_offered:" in block


def test_the_deferred_offer_reads_the_id_that_confirmation_parked():
    """The other end of the same contract."""
    block = _block_after(
        _dependencies_source(),
        "handle_slot_answer(ctx.user_id, message)",
        "try_handle_account_admin_command",
    )
    assert "_safe_pop_pending_report(" in block
    assert "await _offer_team_photo(" in block
