"""WA-291 (live test on Mesiri Test Builders, 13 Nov 2026): a look-up of Main Block's day (labour_attendance,
list_receipts) was sent with Main Block's site and another project's id; the API answers a site and a project that do
not belong together with nothing, and the reply said "nothing recorded at Main Block today" when 12 workers and 95 bags
had been recorded.

Fix: a look-up that names a site carries that site's own project (the code knows it from the person's places).
Guards: a look-up with only a project, or only a site, or the right pair, is left as the model sent it; a write is
never changed here (the write path checks its site and project itself).
"""

from __future__ import annotations

from agent_api.agent import Places, site_project

MAIN, SITE_B = "a34f3deb-0d17-4c35-b08c-b5cb42f71582", "11116a12-47aa-436c-89ba-207cfcd1b926"
LIVE_CHECK, GREEN_VILLA = "8812ee12-3b2b-41b8-b700-47ffe10da2cc", "fee7ee7c-e5d6-436c-88be-7a5ea29cc1ee"
PLACES = Places(sites=((MAIN, "Main Block", LIVE_CHECK), (SITE_B, "Site B", GREEN_VILLA)),
                projects=((LIVE_CHECK, "Live Check Garden"), (GREEN_VILLA, "Green Villa")))


def test_the_reported_look_up_gets_the_sites_own_project() -> None:
    sent = {"site_id": MAIN, "project_id": GREEN_VILLA, "date_from": "2026-11-13", "date_to": "2026-11-13"}
    assert site_project(sent, PLACES) == LIVE_CHECK


def test_guard_the_right_pair_one_of_them_or_an_unknown_site_is_left_alone() -> None:
    assert site_project({"site_id": MAIN, "project_id": LIVE_CHECK}, PLACES) is None
    assert site_project({"site_id": MAIN}, PLACES) is None
    assert site_project({"project_id": GREEN_VILLA}, PLACES) is None
    assert site_project({"site_id": "not-theirs", "project_id": GREEN_VILLA}, PLACES) is None
