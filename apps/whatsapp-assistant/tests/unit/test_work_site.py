"""WA-45: where the sender works today -- the morning question, the tap that
answers it, mid-day switches, saves that keep the site, and new sites."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from backend.ports import ProjectSummary, SiteSummary
from context.active_context import RedisActiveContextStore
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent import toolbox as tb
from runtime.agent import work_site as ws
from runtime.agent.gateway import StepResult
from runtime.agent.journey_gateway import JourneyGateway
from runtime.agent.prompt import AgentContext, render_context
from runtime.agent.tools import CREATE_PROJECT, CREATE_SITE, ScopeLookup, to_candidate

ORG, USER = "org-1", "user-1"
P_A, P_B = ProjectSummary("pa", "Project A"), ProjectSummary("pb", "Project B")
A1, B1, B2 = SiteSummary("a1", "Site A", "pa"), SiteSummary("b1", "Site A", "pb"), SiteSummary("b2", "Site B", "pb")
# 06:30 India time, 22 Oct.
MORNING = dt.datetime(2026, 10, 22, 1, 0, tzinfo=dt.UTC)


def _actor(*sites, name="Suresh Kumar"):
    return SimpleNamespace(
        organization_id=ORG,
        user_id=USER,
        full_name=name,
        role="SITE_ENGINEER",
        timezone="Asia/Kolkata",
        projects=[P_A, P_B],
        sites=list(sites),
    )


def _message(text="50 bags cement arrived", *, tap=None, modality=InputModality.TEXT):
    return NormalizedMessage(
        message_id="wamid.1",
        sender=SenderInfo(wa_id="919000000002", profile_name="Suresh"),
        timestamp=MORNING,
        modality=InputModality.INTERACTIVE if tap else modality,
        text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
    )


def _work_site(now=MORNING):
    redis = FakeRedis()
    store = RedisActiveContextStore(redis, clock=lambda: now)
    return ws.WorkSite(active_context=store, redis=redis, clock=lambda: now), store


# --------------------------------------------------------------- the day


def test_today_lasts_until_midnight_in_the_company_time_zone():
    assert ws.seconds_until_midnight(MORNING, "Asia/Kolkata") == 17 * 3600 + 30 * 60
    late = dt.datetime(2026, 10, 22, 18, 29, 30, tzinfo=dt.UTC)  # 23:59:30 India
    assert ws.seconds_until_midnight(late, "Asia/Kolkata") == 60  # never less than a minute
    assert ws.seconds_until_midnight(MORNING, "Not/AZone") == 17 * 3600 + 30 * 60


# --------------------------------------------------------------- the morning question


async def test_someone_with_one_site_is_never_asked():
    work_site, _ = _work_site()
    assert await work_site.morning_question(_message(), _actor(A1)) is None


async def test_the_first_message_of_the_day_asks_where_they_work_and_waits():
    work_site, _ = _work_site()
    question = await work_site.morning_question(_message(), _actor(A1, B1, B2))

    assert question is not None
    assert question.text == "Good morning, Suresh! 👷\nWhere are you working today?"
    assert question.list_button_label == "Choose site"
    # Same site name under two projects: the project tells them apart.
    assert [(r.id, r.title, r.description) for r in question.list_rows] == [
        ("today_site:a1", "Site A", "Project A"),
        ("today_site:b1", "Site A", "Project B"),
        ("today_site:b2", "Site B", "Project B"),
    ]


async def test_the_owner_is_not_asked_every_morning():
    work_site, _ = _work_site()
    owner = _actor(A1, B1, B2)
    owner.role = "ADMIN"
    assert await work_site.morning_question(_message(), owner) is None


async def test_a_message_that_names_a_site_is_not_asked():
    work_site, _ = _work_site()
    assert await work_site.morning_question(_message("20 masons at site b"), _actor(A1, B2)) is None


async def test_once_today_is_set_nobody_is_asked_again():
    work_site, _ = _work_site()
    actor = _actor(A1, B2)
    await work_site.set_today(actor, project_id=None, site_id="b2")
    assert await work_site.morning_question(_message(), actor) is None
    assert await work_site.today(actor) == ("pb", "b2")


async def test_yesterdays_site_comes_first_tomorrow():
    yesterday, _ = _work_site(MORNING - dt.timedelta(days=1))
    actor = _actor(A1, B1, B2)
    await yesterday.set_today(actor, project_id="pb", site_id="b2")
    # Same Redis, the next morning: today's slot has expired, "last" has not.
    today = ws.WorkSite(
        active_context=RedisActiveContextStore(yesterday._redis, clock=lambda: MORNING),
        redis=yesterday._redis,
        clock=lambda: MORNING,
    )
    question = await today.morning_question(_message(), actor)
    assert question.list_rows[0].id == "today_site:b2"
    assert question.list_rows[0].description == "Last time · Project B"


async def test_a_photo_or_a_tap_never_gets_the_morning_question():
    work_site, _ = _work_site()
    actor = _actor(A1, B2)
    assert await work_site.morning_question(_message(modality=InputModality.IMAGE), actor) is None
    assert await work_site.morning_question(_message(tap="cat_material"), actor) is None


# --------------------------------------------------------------- the tap


async def test_the_tap_sets_today_and_hands_back_the_waiting_message():
    work_site, store = _work_site()
    actor = _actor(A1, B2)
    await work_site.morning_question(_message("50 bags cement arrived"), actor)

    reply, parked = await work_site.handle_tap(_message("Site B", tap="today_site:b2"), actor)

    assert reply.text.startswith("👍 Site B (Project B) for today.")
    assert [m.text for m in parked] == ["50 bags cement arrived"]
    active = await store.get_active_context(organization_id=ORG, user_id=USER)
    assert (active.project_id, active.site_id) == ("pb", "b2")
    # The waiting message runs once: a second tap has nothing to run.
    _, again = await work_site.handle_tap(_message("Site B", tap="today_site:b2"), actor)
    assert again == []


async def test_a_tap_on_a_site_they_lost_access_to_changes_nothing():
    work_site, store = _work_site()
    reply, parked = await work_site.handle_tap(_message("Site X", tap="today_site:gone"), _actor(A1, B2))
    assert "isn't one of yours" in reply.text and parked == []
    assert await store.get_active_context(organization_id=ORG, user_id=USER) is None


async def test_a_second_message_before_the_tap_waits_too():
    """V1 audit SIT-02: the cement message was dropped by the masons one."""
    work_site, _ = _work_site()
    actor = _actor(A1, B2)
    await work_site.morning_question(_message("50 bags cement arrived"), actor)
    again = await work_site.morning_question(_message("12 masons today"), actor)
    assert again.text.startswith("Got it, that waits too")
    assert [r.id for r in again.list_rows] == ["today_site:a1", "today_site:b2"]

    _, parked = await work_site.handle_tap(_message("Site B", tap="today_site:b2"), actor)
    assert [m.text for m in parked] == ["50 bags cement arrived", "12 masons today"]


async def test_a_message_parked_before_the_change_still_runs():
    work_site, _ = _work_site()
    actor = _actor(A1, B2)
    old = _message("50 bags cement arrived").model_dump(mode="json")
    await work_site._redis.set_json(f"{ORG}:user:{USER}:work_site:parked", old)
    _, parked = await work_site.handle_tap(_message("Site B", tap="today_site:b2"), actor)
    assert [m.text for m in parked] == ["50 bags cement arrived"]


async def test_a_typed_site_name_answers_the_question():
    """V1 audit SIT-03: typing "Site B" switched but lost the cement entry."""
    work_site, store = _work_site()
    actor = _actor(A1, B2)
    await work_site.morning_question(_message("50 bags cement arrived"), actor)

    reply, parked = await work_site.handle_typed(_message("at site b."), actor)

    assert reply.text.startswith("👍 Site B (Project B) for today.")
    assert [m.text for m in parked] == ["50 bags cement arrived"]
    active = await store.get_active_context(organization_id=ORG, user_id=USER)
    assert active.site_id == "b2"


async def test_a_typed_name_is_only_an_answer_when_something_waits_and_it_is_one_site():
    work_site, _ = _work_site()
    assert await work_site.handle_typed(_message("Site B"), _actor(A1, B2)) is None  # nothing waiting
    await work_site.morning_question(_message("50 bags cement arrived"), _actor(A1, B1, B2))
    assert await work_site.handle_typed(_message("Site A"), _actor(A1, B1, B2)) is None  # two "Site A"s
    assert await work_site.handle_typed(_message("20 masons at Site B"), _actor(A1, B1, B2)) is None


async def test_the_waiting_message_lasts_until_midnight_not_two_hours():
    """V1 audit SIT-04: a tap after 2 hours found nothing to run."""
    work_site, _ = _work_site()
    ttls: dict[str, int | None] = {}
    real_set = work_site._redis.set_json

    async def set_json(key, value, *, ttl_seconds=None):
        ttls[key] = ttl_seconds
        await real_set(key, value, ttl_seconds=ttl_seconds)

    work_site._redis.set_json = set_json
    await work_site.morning_question(_message("50 bags cement arrived"), _actor(A1, B2))
    assert ttls[f"{ORG}:user:{USER}:work_site:parked"] == 17 * 3600 + 30 * 60  # 06:30 -> midnight India


async def test_any_other_tap_is_not_ours():
    work_site, _ = _work_site()
    assert await work_site.handle_tap(_message("Yes", tap="confirm_yes"), _actor(A1, B2)) is None


# --------------------------------------------------------------- "now at Site B"


class FakeGateway:
    def __init__(self):
        self.switched: list = []

    async def set_work_site(self, *, project_id, site_id):
        self.switched.append((project_id, site_id))
        return "Site B (Project B)"


def _scope():
    return ScopeLookup(
        projects=(("pa", "Project A"), ("pb", "Project B")),
        sites=(("a1", "Site A", "pa"), ("b2", "Site B", "pb")),
    )


async def test_now_at_site_b_switches_today():
    gateway = FakeGateway()
    box = tb.AgentToolbox(gateway, _scope(), "now at site b")
    out = await box.handle("set_work_site", {"site": "site b"})
    assert gateway.switched == [(None, "b2")]
    assert out.content["status"] == "work_site_set"
    assert out.content["site"] == "Site B (Project B)"
    assert box.saved == [] and box.attempted_writes == 0  # nothing for the Save card


async def test_a_site_that_is_not_theirs_is_asked_never_guessed():
    gateway = FakeGateway()
    box = tb.AgentToolbox(gateway, _scope(), "now at green villa")
    out = await box.handle("set_work_site", {"site": "Green Villa"})
    assert gateway.switched == []
    assert out.content["status"] == "choose"
    assert box.parked.text == "Which site are you at?"
    assert [b.title for b in box.parked.buttons] == ["Site A", "Site B"]


# --------------------------------------------------------------- new sites / projects


def test_create_site_goes_to_the_site_create_workflow_under_the_named_project():
    candidate = to_candidate(CREATE_SITE, {"name": "Site C", "project": "project b"}, _scope())
    assert candidate.semantic_type is SemanticType.SITE_CREATE
    assert candidate.fields == {"name": "Site C", "project_id": "pb"}


def test_create_site_without_a_project_leaves_it_to_the_context():
    candidate = to_candidate(CREATE_SITE, {"name": " Site C ", "location": "Kakkanad"}, _scope())
    assert candidate.fields == {"name": "Site C", "location": "Kakkanad"}


def test_create_project_goes_to_the_project_create_workflow():
    candidate = to_candidate(CREATE_PROJECT, {"name": "Green Villa", "location": "Aluva"}, _scope())
    assert candidate.semantic_type is SemanticType.PROJECT_CREATE
    assert candidate.fields == {"name": "Green Villa", "location": "Aluva"}


def _confirmed(action_type, *, project_id="pb", site_id=None, row_id="new-site", status=ExecutionStatus.SUCCEEDED):
    draft = SimpleNamespace(action_type=action_type, project_id=project_id, site_id=site_id)
    return SimpleNamespace(
        result=SimpleNamespace(confirmed_action=SimpleNamespace(draft_action=draft)),
        execution_result=SimpleNamespace(status=status, material_row_id=row_id),
    )


def test_a_new_site_is_found_after_its_yes():
    assert ws.created_site(_confirmed(DraftActionType.CREATE_SITE)) == ("pb", "new-site")
    assert ws.created_site(_confirmed(DraftActionType.CREATE_PROJECT)) is None
    assert ws.created_site(_confirmed(DraftActionType.CREATE_SITE, status=ExecutionStatus.REJECTED)) is None


# --------------------------------------------------------------- saves keep the site


async def test_any_save_keeps_its_site_for_the_rest_of_the_day():
    remembered: list = []

    async def set_today(project_id, site_id):
        remembered.append((project_id, site_id))
        return "Site B (Project B)"

    labour = _confirmed(DraftActionType.RECORD_LABOUR_ATTENDANCE, site_id="b2")

    class Saving(JourneyGateway):
        async def _run(self, candidate, *, text):  # the classic run is covered elsewhere
            self.handled.append(labour)
            return StepResult("saved", text="Labour recorded")

    gateway = Saving(
        message=_message(),
        save_now=None, undo=None, followups=None, held_prompt=None,
        set_today_site=set_today,
    )
    step = await gateway.run(to_candidate("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]}, _scope()), text="3 masons")

    assert step.status == "saved"
    assert remembered == [("pb", "b2")]


# --------------------------------------------------------------- what the model is told


def test_the_model_is_told_where_they_work_today():
    base = dict(user_name="Suresh", role="SITE_ENGINEER", company="Acme", now=MORNING,
                sites=(("Site A", "Project A"), ("Site B", "Project B")))
    text = render_context(AgentContext(**base, work_site="Site B (Project B)"))
    assert "Working today at: Site B (Project B). Use it unless they name another site." in text
    assert "Working today" not in render_context(AgentContext(**base))


def test_create_site_reaches_the_real_site_create_workflow_and_its_yes_no():
    """The tool's understanding follows the classic route to the existing
    workflow, whose own draft and Yes/No prompt are used unchanged."""
    from canonicalization.mapping import REQUIRED_FIELDS, resolve_event_type
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from planner.routing import WORKFLOW_KEY_BY_EVENT
    from workflows.site_create import nodes

    candidate = to_candidate(CREATE_SITE, {"name": "Site C", "project": "Project B"}, _scope())
    event = resolve_event_type(candidate.semantic_type, candidate.fields)
    assert all(candidate.fields.get(f) for f in REQUIRED_FIELDS[event])
    assert WORKFLOW_KEY_BY_EVENT[event] is WorkflowKey.SITE_CREATE

    import uuid

    project = str(uuid.uuid4())
    state = {
        "workflow_instance_id": str(uuid.uuid4()), "correlation_id": "cor_1",
        "organization_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()),
        "project_id": project, "collected_fields": dict(candidate.fields),
    }
    draft = nodes.build_draft(state)["draft_action"]
    assert draft.action_type is DraftActionType.CREATE_SITE
    assert (str(draft.project_id), draft.fields["name"]) == (project, "Site C")
    prompt = nodes.request_confirmation({**state, "draft_action": draft})["pending_prompt"]
    assert "Create a new site: *Site C*" in prompt
