"""SS-74c: the player's rules cover every kind the plan has (guided-demo-plan.md section 18.4).

The whole plan is played on a real database by apps/whatsapp-assistant/tests/integration/test_sandbox_player_postgres.py;
this keeps the tables complete so a new kind of entry can't be added without a page and a way to tick it.
"""

from __future__ import annotations

from mesiri.application.learn import sample_plan as sp
from mesiri.application.learn import sandbox_player as player

#: Kinds ticked by what they leave behind (``_outcome_done``) rather than by who saved a record.
_BY_OUTCOME = {"stage", "issue_resolve", "conditions", "boq_count", "contract", "boq_import"}


def test_every_kind_has_a_page_and_a_way_to_be_ticked():
    kinds = set(sp.KINDS)
    assert kinds <= set(player.PAGE)
    assert kinds <= set(player._DONE) | _BY_OUTCOME
    assert not set(player._DONE) & _BY_OUTCOME


def test_pages_are_real_dashboard_pages():
    import re
    from pathlib import Path

    module_map = (Path(__file__).resolve().parents[3] / "apps" / "dashboard" / "src" / "lib" / "module-map.ts").read_text()
    built = set(re.findall(r"url: '([^'?]+)", module_map)) | {"/today", "/issues", "/labour"}
    assert {p.split("?")[0] for p in player.PAGE.values()} <= built


def test_at_most_a_week_at_once():
    assert player.MAX_DAYS == 7
