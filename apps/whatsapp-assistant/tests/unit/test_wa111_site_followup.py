"""[111] follow-up to the sites audit (SIT-01/02, live 25 Oct).

SIT-02: "5 mason vannu" asks which site; a second update sent before the tap
asked it again and replaced the first, so the tap saved only the cement. The
sequence is replayed here through the real agent turn (runner, toolbox,
turn, wait store) with the model's tool calls scripted and a gateway that
asks the site question the way the entries do."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.ports import ProjectSummary, SiteSummary
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent import site_match
from runtime.agent import toolbox as tb
from runtime.agent.entry_base import Say, choose
from runtime.agent.gateway import StepResult
from runtime.agent.runner import AgentRunner
from runtime.agent.site_wait import SiteWaitStore
from runtime.agent.turn import AgentTurnDeps, run_agent_turn

GREEN = SiteSummary("s-green", "Green Villa, Kakkanad", "p1")
SITE_B = SiteSummary("s-b", "Site B", "p1")
ACTOR = SimpleNamespace(
    organization_id="org-1",
    user_id="u1",
    full_name="Ilan",
    role="SUPERVISOR",
    org_name="TEST",
    timezone="Asia/Kolkata",
    projects=[ProjectSummary("p1", "Project One")],
    sites=[GREEN, SITE_B],
    location=None,
)


class _Redis:
    def __init__(self) -> None:
        self.data: dict = {}

    def namespaced(self, *parts):  # noqa: ANN002, ANN201
        return ":".join(parts)

    async def set_json(self, key, value, *, ttl_seconds=None):  # noqa: ANN001, ANN201
        self.data[key] = value

    async def get_json(self, key):  # noqa: ANN001, ANN201
        return self.data.get(key)

    async def delete(self, *keys):  # noqa: ANN002, ANN201
        for key in keys:
            self.data.pop(key, None)


class _Gateway:
    """Saves when the candidate names a site; asks the site question when not
    (what SiteEntry/LabourEntry/MaterialEntry do through ``settle``)."""

    handled: list = []
    current_call = None

    def __init__(self, saved: list) -> None:
        self.saved = saved
        self.card_items: list = []

    async def run(self, candidate, *, text):  # noqa: ANN001, ANN201
        fields = candidate.fields
        site = fields.get("site_id") or fields.get("site_name")
        if not site:
            say = choose("Which site is this for?", [GREEN.name, SITE_B.name], "site")
            return StepResult(
                "choose", text=say.text, reply=tb.question_reply(say.question, list(say.options), awaiting="site"),
                awaiting="site",
            )
        name, args = self.current_call
        summary = _summary(name, args, site)
        self.saved.append((name, site, summary))
        return StepResult("saved", text="✅ Recorded.", summary=summary, workflow_key=name)

    async def finish(self):  # noqa: ANN201
        return None


def _summary(name: str, args: dict, site: str) -> str:
    if name == "save_labour":
        return "5 workers (5 mason)"
    return "Cement used: 10 bags"


def _message(text: str, n: int, tap: str | None = None) -> NormalizedMessage:
    return NormalizedMessage(
        message_id=f"wamid.in.{n}",
        correlation_id=f"corr-{n}",
        sender=SenderInfo(wa_id="919000000002", profile_name="Ilan"),
        timestamp=dt.datetime(2026, 10, 25, 8, tzinfo=dt.UTC),
        modality=InputModality.INTERACTIVE if tap else InputModality.TEXT,
        text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
    )


LABOUR = ("save_labour", {"workers": [{"trade": "mason", "count": 5}]})
CEMENT = ("save_material_usage", {"material": "cement", "quantity": 10, "unit": "bag"})


async def _turn(text: str, n: int, script: list, store: SiteWaitStore, saved: list, sent: list):
    deps = AgentTurnDeps(
        runner=AgentRunner(FakeToolCallingProvider(script)),
        make_gateway=lambda message, language: _Gateway(saved),
        send_spec=AsyncMock(side_effect=lambda spec, wa: sent.append(spec)),
        transcribe=None,
        message_logger=AsyncMock(),
        site_wait=store,
    )
    return await run_agent_turn(_message(text, n), ACTOR, deps)


async def test_sit02_live_sequence_both_entries_are_saved_on_the_answer():
    """5 mason vannu -> site question; 10 bags cement used -> asked again; tap
    Site B -> BOTH are saved, labour first, at Site B."""
    store, saved, sent = SiteWaitStore(_Redis()), [], []
    await _turn("5 mason vannu", 1, [[LABOUR], "Which site?"], store, saved, sent)
    assert saved == [] and sent[-1].text == "Which site is this for?"

    await _turn("10 bags cement used", 2, [[CEMENT], "Which site?"], store, saved, sent)
    assert saved == []
    # One question, in code; it says two updates wait.
    assert "holding 2" in sent[-1].text and sent[-1].text.endswith("Which site is this for?")
    assert [i["tool"] for i in await store.get(ACTOR)] == ["save_labour", "save_material_usage"]

    # The tap: the model sees the answer and saves the last thing asked.
    cement_b = ("save_material_usage", {**CEMENT[1], "site": "Site B"})
    await _turn("Site B", 3, [[cement_b], "Done."], store, saved, sent)

    assert [(tool, site) for tool, site, _ in saved] == [
        ("save_labour", "s-b"),
        ("save_material_usage", "s-b"),
    ]
    assert [s for _, _, s in saved] == ["5 workers (5 mason)", "Cement used: 10 bags"]
    assert await store.get(ACTOR) == []


async def test_the_answer_releases_the_queue_even_if_the_model_saves_nothing():
    store, saved, sent = SiteWaitStore(_Redis()), [], []
    await _turn("5 mason vannu", 1, [[LABOUR], "?"], store, saved, sent)
    await _turn("10 bags cement used", 2, [[CEMENT], "?"], store, saved, sent)
    await _turn("Site B", 3, ["Okay."], store, saved, sent)
    assert [tool for tool, _, _ in saved] == ["save_labour", "save_material_usage"]
    assert await store.get(ACTOR) == []


async def test_the_model_saving_an_earlier_entry_itself_does_not_double_it():
    store, saved, sent = SiteWaitStore(_Redis()), [], []
    await _turn("5 mason vannu", 1, [[LABOUR], "?"], store, saved, sent)
    await _turn("10 bags cement used", 2, [[CEMENT], "?"], store, saved, sent)
    labour_b = ("save_labour", {**LABOUR[1], "site": "Site B"})
    cement_b = ("save_material_usage", {**CEMENT[1], "site": "Site B"})
    await _turn("Site B", 3, [[labour_b, cement_b], "Done."], store, saved, sent)
    assert [tool for tool, _, _ in saved] == ["save_labour", "save_material_usage"]


async def test_an_unrelated_message_leaves_the_waiting_saves_unsaved_and_says_so():
    store, saved, sent = SiteWaitStore(_Redis()), [], []
    await _turn("5 mason vannu", 1, [[LABOUR], "?"], store, saved, sent)
    await _turn("hello", 2, ["Hi!"], store, saved, sent)
    assert saved == []
    assert "5 mason vannu" in sent[-1].text and "no site was picked" in sent[-1].text
    assert await store.get(ACTOR) == []


async def test_a_question_the_model_asks_about_the_answer_keeps_the_queue():
    store, saved, sent = SiteWaitStore(_Redis()), [], []
    await _turn("5 mason vannu", 1, [[LABOUR], "?"], store, saved, sent)
    ask = ("ask_user", {"question": "Type the site name"})
    await _turn("Something else", 2, [[ask], "Type the site name"], store, saved, sent)
    assert [i["tool"] for i in await store.get(ACTOR)] == ["save_labour"]


def test_the_fixed_site_question_follows_the_message_language():
    from runtime.agent.entry_base import site_words

    english = SimpleNamespace(text="5 mason came")
    manglish = SimpleNamespace(text="innu 5 mason vannu, 10 bag cement upayogichu")
    assert site_words(english, "site_q") == "Which site is this for?"
    assert site_words(manglish, "site_q") == "Ee update ethu site-inte aanu?"
    assert site_words(english, "no_site", said="Site C") == 'I don\'t have a site called "Site C". Which site?'


# -- titles (item 3) ---------------------------------------------------------


def test_button_and_row_titles_fit_whatsapp_and_are_never_cut_mid_word():
    labels = ["Green Villa, Kakkanad", "Site B", "Tower 1 North Wing Block C", "Site A · Project B"]
    reply = tb.site_reply("Which site is this for?", labels)
    assert reply.buttons is None or reply.buttons == ()
    assert [r.title for r in reply.list_rows] == [
        "Green Villa, Kakkanad",
        "Site B",
        "Tower 1 North Wing…",
        "Site A · Project B",
    ]
    assert all(len(r.title) <= 24 for r in reply.list_rows)
    assert reply.list_rows[2].description == "Tower 1 North Wing Block C"
    assert reply.list_rows[0].description == ""


def test_short_names_stay_buttons_and_a_long_one_makes_it_a_list():
    short = tb.site_reply("Which site is this for?", ["Green Villa", "Site B"])
    assert [b.title for b in short.buttons] == ["Green Villa", "Site B"]
    long = tb.site_reply("Which site is this for?", ["Green Villa, Kakkanad", "Site B"])
    assert not long.buttons and long.list_rows[0].description == ""


@pytest.mark.parametrize("limit", [20, 24])
@pytest.mark.parametrize(
    "label",
    [
        "Green Villa, Kakkanad",
        "Green Villa · Kakkanad Tower Project",
        "Supercalifragilisticexpialidocious Block",
        "A very long site name with many words in it",
    ],
)
def test_short_title_property(label, limit):
    title = site_match.short_title(label, limit)
    assert len(title) <= limit
    if len(title) < len(label):
        assert title.endswith("…") or "·" in title  # shortened between words, or by initials


# -- item 4: only real sites are offered -------------------------------------


async def test_sit01_site_c_is_never_a_button_and_every_real_site_is_offered():
    from tests.unit.test_sites_audit import U_ALL, _entry, _issue

    out = await _issue(_entry(U_ALL), site_name="Site C")
    assert isinstance(out, Say) and out.status == "choose" and out.awaiting == "site"
    assert out.question == 'I don\'t have a site called "Site C". Which site?'
    assert "Site C" not in out.options
    assert set(out.options) == {"Site A · Project A", "Tower 1", "Site A · Project B", "Site B"}
    reply = tb.question_reply(out.question, list(out.options), awaiting="site")
    assert all(r.title != "Site C" for r in (reply.list_rows or reply.buttons))


# -- item 5: the team offer counts the members first -------------------------


class _Team:
    def __init__(self, others):  # noqa: ANN001
        self.others = others

    async def count_other_members(self, *, project_id, user_id):  # noqa: ANN001, ANN201
        return self.others


async def _offer(others):  # noqa: ANN001, ANN202
    from tests.unit.test_project_setup_offer_trigger import (
        PRJ,
        _confirmed,
        _FakeActor,
        _handled,
    )

    from mesiri_contracts.assistant.draft_action import DraftActionType
    from runtime.inbound_journey.seeding import _offer_project_setup

    class _Store:
        def __init__(self) -> None:
            self.set_calls: list = []

        async def set_offer(self, **kw):  # noqa: ANN003, ANN201
            self.set_calls.append(kw)

    store, sent = _Store(), []

    async def send_reply(spec, wa_id):  # noqa: ANN001, ANN202
        sent.append(spec)

    handled = _handled(_confirmed(DraftActionType.CREATE_SITE, project_id=PRJ), material_row_id=str(uuid.uuid4()))
    ok = await _offer_project_setup(handled, store, _FakeActor(), "wa", send_reply, _Team(others))
    return ok, store, sent


async def test_a_project_with_other_members_gets_no_no_team_message():
    ok, store, sent = await _offer(2)
    assert ok is False and sent == [] and store.set_calls == []


async def test_only_the_sender_on_it_says_so_not_that_there_is_no_team():
    ok, _, sent = await _offer(0)
    assert ok is True and "Only you are on this project" in sent[0].text and "doesn't have a team" not in sent[0].text


async def test_an_uncountable_team_makes_no_claim_about_it():
    ok, _, sent = await _offer(None)
    assert ok is True and "team yet" not in sent[0].text
