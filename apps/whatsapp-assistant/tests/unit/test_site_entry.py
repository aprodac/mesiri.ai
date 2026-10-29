"""ARCH-02: work done, site issues and expenses from the agent without the classic pipeline.

The fixes canonicalization made and the seeds the pipeline ran come from the
same functions; what changed is that a work entry's date is now resolved
("yesterday" was saved as today on the classic route).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from tests.unit.test_material_entry import (
    MESSAGE,
    ORG,
    PRJ,
    SITE,
    _actor,
    _Context,
    _Modules,
    _Understanding,
)

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.entry_base import Ready, Say
from runtime.agent.site_entry import SiteEntry
from runtime.agent.work_site import NIGHT_GRACE_HOURS


class _Accounts:
    async def list_accounts(self, **kwargs: Any) -> list[Any]:
        return [SimpleNamespace(id="acc-1", name="Site cash"), SimpleNamespace(id="acc-2", name="HDFC")]


def _site_actor() -> Any:
    actor = _actor(SITE)
    actor.organization_id = ORG
    return actor


def _entry(*, modules=None, context=None, **services: Any) -> SiteEntry:
    return SiteEntry(
        context_resolver=context or _Context(),
        org_settings_query=modules,
        actor=_site_actor(),
        **services,
    )


async def _prepare(entry: SiteEntry, semantic_type: SemanticType, message: Any = MESSAGE, **fields: Any):
    candidate = Candidate(semantic_type=semantic_type, fields=fields)
    return await entry.prepare(message, _Understanding(candidate), candidate)


def _yesterday() -> str:
    return (datetime.datetime.now(ZoneInfo("Asia/Kolkata")).date() - datetime.timedelta(days=1)).isoformat()


async def test_work_done_is_ready_with_its_percentage_and_its_stated_date():
    ready = await _prepare(
        _entry(),
        SemanticType.GENERAL_SITE_UPDATE,
        narrative="slab concreting",
        work_type="concreting",
        progress_percent=40,
        occurred_on="yesterday",
        project_id=PRJ,
    )
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.SITE_UPDATE
    assert ready.event.event_type is CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED
    fields = ready.event.fields
    assert fields["progress_percent"] == 40
    assert "40%" in fields["narrative"]
    assert (fields["occurred_date"], fields["occurred_date_source"]) == (_yesterday(), "stated_by_user")
    assert "project_id" not in fields and "occurred_on" not in fields
    assert (str(ready.event.project_id), str(ready.event.site_id)) == (PRJ, SITE)


async def test_an_issue_keeps_its_fields_and_the_engineer_question_prefix():
    ready = await _prepare(
        _entry(),
        SemanticType.SITE_ISSUE,
        issue_type="OTHER",
        severity="LOW",
        narrative="Question for your engineer: can we cast the slab tomorrow?",
    )
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.SITE_ISSUE_REPORT
    assert ready.event.fields["narrative"].startswith("Question for your engineer: ")
    assert ready.event.fields["occurred_date_source"] == "inferred_at_confirmation"


async def test_an_issue_without_its_kind_and_an_expense_without_an_amount_are_refused():
    assert isinstance(await _prepare(_entry(), SemanticType.SITE_ISSUE, narrative="leak"), Say)
    said = await _prepare(_entry(), SemanticType.EXPENSE, amount=0, description="tea")
    assert isinstance(said, Say) and "amount above zero" in said.text


async def test_an_expense_is_seeded_with_the_accounts_to_choose_from():
    ready = await _prepare(_entry(money_account_query=_Accounts()), SemanticType.EXPENSE, amount=500, description="tea")
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.EXPENSE_SUBMIT
    assert [a["id"] for a in ready.event.fields["account_candidates"]] == ["acc-1", "acc-2"]


async def test_a_switched_off_module_is_said_not_saved():
    said = await _prepare(_entry(modules=_Modules(["dpr"])), SemanticType.EXPENSE, amount=500)
    assert isinstance(said, Say) and said.status == "info"
    ready = await _prepare(_entry(modules=_Modules(["dpr"])), SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(ready, Ready)  # issues and work done need "dpr", expenses "finance"


async def test_a_forwarded_message_is_marked_as_the_pipeline_marked_it():
    message = SimpleNamespace(correlation_id="cor_2", message_id="wamid.2", metadata={"forwarded": True})
    ready = await _prepare(_entry(), SemanticType.SITE_ISSUE, message, issue_type="WEATHER")
    assert ready.event.fields["is_forwarded"] is True


async def test_no_project_asks_which_one_and_other_kinds_go_classic():
    said = await _prepare(_entry(context=_Context(project_id=None, site_id=None)), SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(said, Say) and said.status in ("choose", "info")
    assert await _prepare(_entry(), SemanticType.LABOUR_UPDATE, workers=[]) is None


async def test_work_named_only_in_its_quantities_gets_its_work_type():
    """Live golden set, 22 Oct: '50 meter wiring ho gaya' came with the work
    named only inside quantities."""
    ready = await _prepare(
        _entry(),
        SemanticType.GENERAL_SITE_UPDATE,
        narrative="aaj 50 meter wiring ho gaya",
        quantities=[{"work_type": "wiring", "quantity": 50, "unit": "m"}],
    )
    assert ready.event.fields["work_type"] == "wiring"


async def test_work_with_no_site_of_the_senders_says_so_instead_of_failing_at_save():
    """Live 22 Oct (Hospital Project): a PM with custom site access and no site
    got "which site?" with nothing to pick; the save refuses work without one."""
    entry = _entry(context=_Context(site_id=None))
    entry.actor.sites = []
    said = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="slab concreting")
    assert isinstance(said, Say) and said.status == "info"
    assert "not on any site of this project" in said.text
    # Request 104, D: an issue needs a site too -- said plainly, not left to a
    # save that "didn't go through". An expense still goes through without one.
    issue = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(issue, Say) and issue.status == "info" and "not on any site" in issue.text
    expense = await _prepare(entry, SemanticType.EXPENSE, amount=500)
    assert isinstance(expense, Ready) and expense.event.site_id is None


class _Today:
    """The active context: today's site (WA-45) or the last one saved to."""

    def __init__(self, project_id: str, site_id: str) -> None:
        self.slot = SimpleNamespace(project_id=project_id, site_id=site_id)

    async def get_active_context(self, **kwargs: Any) -> Any:
        return self.slot


async def test_todays_site_wins_over_the_context_layers_other_project():
    """Live 22 Oct: an admin set Tower A as today's site; the context layer
    (members-only rule) resolved another project with no site of theirs, and
    the work was refused. Unnamed, today's site from their own list is used."""
    other = "99999999-9999-4999-8999-999999999999"
    entry = _entry(context=_Context(project_id=other, site_id=None))
    entry.active_context = _Today(PRJ, SITE)
    ready = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="slab concreting")
    assert isinstance(ready, Ready)
    assert (str(ready.event.project_id), str(ready.event.site_id)) == (PRJ, SITE)
    # A message that names a project still goes by what it names.
    named = await _prepare(entry, SemanticType.EXPENSE, amount=500, project_name="Other")
    assert isinstance(named, Ready) and str(named.event.project_id) == other


# Review of 22 Oct: loopholes in the direct routes.


async def test_a_pick_the_context_layer_still_refuses_is_not_asked_again():
    context = _Context(ok=False)
    entry = _entry(context=context)
    entry.actor.projects = [SimpleNamespace(id=PRJ, name="Villa")]
    first = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(first, Say) and first.status == "choose"
    again = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER", project_id=PRJ)
    assert isinstance(again, Say) and again.status == "error"  # no second "Which project?"


async def test_a_site_name_two_projects_share_is_matched_within_the_project():
    entry = _entry(context=_Context(site_id=None))
    entry.actor.sites = [
        SimpleNamespace(id=SITE, name="Block A", project_id=PRJ),
        SimpleNamespace(id="55555555-0000-4000-8000-000000000002", name="Block B", project_id=PRJ),
    ]
    asked = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(asked, Say) and asked.status == "choose"
    ready = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER", site_name="block a")
    assert isinstance(ready, Ready) and str(ready.event.site_id) == SITE


async def test_a_site_less_entry_never_overwrites_todays_site():
    class _Store:
        def __init__(self) -> None:
            self.writes: list[dict] = []

        async def get_active_context(self, **kwargs: Any) -> Any:
            return None

        async def set_active_context(self, **kwargs: Any) -> None:
            self.writes.append(kwargs)

    entry = _entry(context=_Context(site_id=None))
    entry.actor.sites = []
    entry.active_context = _Store()
    ready = await _prepare(entry, SemanticType.EXPENSE, amount=500, description="tea")
    await entry.remember(ready)
    assert entry.active_context.writes == []
    entry.actor.sites = [SimpleNamespace(id=SITE, name="Block A", project_id=PRJ)]
    ready = await _prepare(entry, SemanticType.EXPENSE, amount=500, description="tea")
    await entry.remember(ready)
    (write,) = entry.active_context.writes
    # Until the company's midnight plus the night grace, whatever the hour now.
    assert write["site_id"] == SITE and 60 <= write["ttl_seconds"] <= (24 + NIGHT_GRACE_HOURS) * 3600


async def test_todays_site_does_not_override_a_reply_to_another_record():
    other = "99999999-9999-4999-8999-999999999999"
    context = _Context(project_id=other, site_id=None)
    context.ctx.context_source = SimpleNamespace(value="reply_context")
    entry = _entry(context=context)
    entry.active_context = _Today(PRJ, SITE)
    ready = await _prepare(entry, SemanticType.EXPENSE, amount=500)
    assert str(ready.event.project_id) == other


class _OpenWork:
    """Two open plastering activities on the site, as find_open_activities."""

    ROWS = [
        {"activity_id": "a1", "work_type": "plastering", "narrative": "2nd floor plastering"},
        {"activity_id": "a2", "work_type": "plastering", "narrative": "3rd floor plastering"},
    ]

    async def find_open_activities(self, **kwargs: Any) -> list[dict]:
        return self.ROWS


async def test_the_open_work_the_model_names_gets_the_update_not_a_new_activity():
    """User, 22 Oct: "plastering finished" after "started plastering" could
    make a second activity when the code's guess was unsure. The model sees
    the open work and names the one it continues."""
    from runtime.today_context import open_work_label

    entry = _entry(activity_query=_OpenWork())
    entry.actor.organization_id = ORG
    label = open_work_label(_OpenWork.ROWS[1])
    assert label == "Plastering (3rd floor plastering)"
    ready = await _prepare(
        entry, SemanticType.GENERAL_SITE_UPDATE, narrative="plastering finished", work_type="plastering",
        update_kind="completed", continues=label,
    )
    fields = ready.event.fields
    assert fields["activity_id"] == "a2" and fields["_target_resolved"] is True
    assert "_open_activity_candidates" not in fields and "continues" not in fields


async def test_a_name_that_fits_several_or_none_is_left_to_the_usual_matching():
    entry = _entry(activity_query=_OpenWork())
    entry.actor.organization_id = ORG
    for said in ("plastering", "brickwork"):
        ready = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="done", continues=said)
        assert "activity_id" not in ready.event.fields
        assert len(ready.event.fields["_open_activity_candidates"]) == 2


async def test_a_loose_name_goes_to_the_work_this_chat_last_touched():
    """Two open plastering jobs and "plastering finished": the one this
    conversation last touched is the classic route's first pick."""
    entry = _entry(activity_query=_OpenWork())
    entry.actor.organization_id = ORG

    async def remembered() -> str:
        return "a1"

    entry.remembered_activity = remembered
    ready = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="done", continues="plastering")
    assert ready.event.fields["activity_id"] == "a1"
    # Without a continues the model may mean new work: the memory is not used.
    ready = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="started brickwork")
    assert "activity_id" not in ready.event.fields


def test_the_open_work_line_names_each_activity_once():
    from runtime.today_context import render_open_work_line

    line = render_open_work_line("Tower A (Hospital Project)", _OpenWork.ROWS)
    assert line.startswith("Open work at Tower A (Hospital Project) (started, not finished): ")
    assert "Plastering (2nd floor plastering); Plastering (3rd floor plastering)." in line
    assert render_open_work_line("Tower A", []) is None


class _Units:
    """The units list: only these spellings are known."""

    KNOWN = {"sq ft": "sqft", "sqft": "sqft", "meters": "m"}

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def resolve_unit(self, text: str) -> dict[str, Any] | None:
        self.asked.append(text)
        code = self.KNOWN.get(text.strip().lower())
        return {"code": code} if code else None


async def test_wrk02_a_unit_the_list_does_not_know_is_asked_not_lost():
    entry = _entry(catalog_query=_Units())
    said = await _prepare(
        entry, SemanticType.GENERAL_SITE_UPDATE,
        narrative="plastering done", work_type="plastering", quantity=50, unit="furlongs",
    )
    assert isinstance(said, Say) and said.status == "choose" and said.awaiting == "unit"
    assert "furlongs" in said.question and "sq ft" in said.options
    # every option is itself a unit the list knows or resolves (they come back as the answer)
    assert len(said.options) <= 10


async def test_wrk02_a_known_unit_goes_straight_through_and_no_quantity_asks_nothing():
    units = _Units()
    ready = await _prepare(
        _entry(catalog_query=units), SemanticType.GENERAL_SITE_UPDATE,
        narrative="tiling", work_type="tiling", quantities=[{"work_type": "tiling", "quantity": 200, "unit": "sq ft"}],
    )
    assert isinstance(ready, Ready) and units.asked == ["sq ft"]
    ready = await _prepare(_entry(catalog_query=units), SemanticType.GENERAL_SITE_UPDATE, narrative="tiling done", work_type="tiling")
    assert isinstance(ready, Ready) and units.asked == ["sq ft"]


async def test_wrk02_every_quantity_of_a_message_is_checked():
    said = await _prepare(
        _entry(catalog_query=_Units()), SemanticType.GENERAL_SITE_UPDATE,
        narrative="tiling and wiring", work_type="tiling",
        quantities=[{"work_type": "tiling", "quantity": 200, "unit": "sq ft"},
                    {"work_type": "wiring", "quantity": 50, "unit": "reels"}],
    )
    assert isinstance(said, Say) and "reels" in said.question and "wiring" in said.question


def test_wrk04_past_six_open_jobs_the_rest_are_counted_not_dropped():
    from runtime.today_context import render_open_work_line

    rows = [{"activity_id": f"a{i}", "work_type": f"job{i}", "narrative": f"job{i}"} for i in range(1, 10)]
    line = render_open_work_line("Tower A", rows)
    assert "Job6" in line and "Job7" not in line
    assert "and 3 more open" in line
    assert "more open" not in render_open_work_line("Tower A", rows[:6])


def test_wrk05_with_no_site_chosen_the_open_work_is_shown_under_each_site():
    from runtime.today_context import render_open_work_line

    rows = [
        {"activity_id": "a1", "site_id": "s1", "work_type": "plastering", "narrative": "plastering"},
        {"activity_id": "a2", "site_id": "s2", "work_type": "wiring", "narrative": "wiring"},
    ]
    line = render_open_work_line(None, rows, site_names={"s1": "Site A", "s2": "Site B"})
    assert "Site A: Plastering" in line and "Site B: Wiring" in line


async def test_wrk04_the_seventh_job_is_continued_not_started_again():
    candidates = [
        {"activity_id": f"a{i}", "work_type": f"job{i}", "narrative": f"started job{i}"} for i in range(1, 9)
    ]

    class _Many:
        async def find_open_activities(self, **kwargs: Any) -> list[dict[str, Any]]:
            assert kwargs["limit"] >= 8 if "limit" in kwargs else True
            return candidates

    entry = _entry(activity_query=_Many())
    entry.actor.organization_id = ORG
    ready = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="job7 finished", continues="job7")
    assert ready.event.fields["activity_id"] == "a7"


async def test_an_owner_with_one_site_is_never_asked_which_site():
    """SS-18: the welcome screen waits for a new owner's first update. Signup
    made one project with one site, so the update must land on it straight
    away -- a "which site?" there would leave the screen waiting -- even when
    the context layer resolved no site for the message."""
    entry = _entry(context=_Context(site_id=None))
    entry.actor.role = "ADMIN"
    entry.actor.sites = [SimpleNamespace(id=SITE, name="Green Villa", project_id=PRJ)]

    work = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="slab shuttering done")
    assert isinstance(work, Ready)
    assert str(work.event.site_id) == SITE

    issue = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="MATERIAL_SHORTAGE")
    assert isinstance(issue, Ready)
    assert str(issue.event.site_id) == SITE
