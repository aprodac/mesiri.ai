"""WEB-87: a question's ripple on Live: the answer, what Mesiri read for it, and the day's messages it was built from.

The question's turn already keeps what it looked up (each call's tool and arguments). The guards that matter:
only today's *saved* messages from *before* the question count; only at the site it read and of the material it
read (a message with no material record is then left out, never guessed); only what this viewer may see; and a
question that read nothing built from messages (projects, units) has no ripple at all."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import HTTPException

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import effects, live_feed
from mesiri.domains.dpr import router as dpr_router

ORG, P1 = uuid.uuid4(), uuid.uuid4()
S1, S2 = uuid.uuid4(), uuid.uuid4()
CEMENT, STEEL = str(uuid.uuid4()), str(uuid.uuid4())
TODAY = datetime.date(2026, 11, 14)


def _saved(tool, rid, summary):
    return {"tools": [tool], "saved": [{"tool": tool, "status": 201, "summary": summary, "id": rid}]}


def _ask(*reads):
    return {"tools": [r[0] for r in reads], "reads": [{"tool": t, "args": a} for t, a in reads]}


def _row(id_, turns, site=S1, sender="Ravi", site_name="Main block", project=P1, text="msg", reply="ok"):
    return {"id": id_, "type": "text", "text": text, "reply": reply, "project_id": project, "site_id": site,
            "site_name": site_name, "sender_name": sender, "turns": turns}


# --- the feed: what a question looked up --------------------------------------------------------------------------------

def test_a_question_that_read_the_stock_has_its_own_ripple():
    row = _row("q1", [_ask(("search_materials", {"q": "cement"}),
                           ("stock_summary", {"site_id": str(S1), "material_id": CEMENT}))])
    out = live_feed.classify(row)
    assert out["kind"] == "question" and out["state"] == "answered"
    assert out["records"] == [{"kind": "answer", "id": "q1"}]
    assert out["looked"] == [{"tool": "stock_summary", "site_id": str(S1), "material_id": CEMENT}]


def test_guard_a_question_that_read_nothing_built_from_messages_has_no_ripple():
    out = live_feed.classify(_row("q2", [_ask(("list_projects", {}), ("list_units", {}))]))
    assert out["kind"] == "question" and out["records"] == [] and out["looked"] == []


def test_guard_a_save_that_also_looked_something_up_keeps_its_own_records():
    rid = str(uuid.uuid4())
    turn = {**_saved("record_receipt", rid, "50 bags cement"), "reads": [{"tool": "stock_summary", "args": {}}]}
    out = live_feed.classify(_row("m", [turn]))
    assert out["records"] == [{"kind": "material_receipt", "id": rid}] and out["looked"] == []


def test_each_tool_is_kept_once_with_the_ids_it_named():
    turns = [_ask(("labour_attendance", {"site_id": str(S1)}), ("labour_attendance", {"site_id": str(S2)}),
                  ("day_summary", {}))]
    assert live_feed.looked(turns) == [{"tool": "labour_attendance", "site_id": str(S1), "material_id": None},
                                       {"tool": "day_summary", "site_id": None, "material_id": None}]


def test_every_answer_read_is_a_tool_with_kinds_live_knows():
    for _words, kinds, question, opens in live_feed.ANSWERS.values():
        assert set(kinds) <= set(live_feed.KIND_LABELS) and 1 <= question <= 6 and opens.startswith("/")


# --- the cards ----------------------------------------------------------------------------------------------------------

def test_the_cards_say_the_answer_what_was_read_and_the_messages_behind_it():
    f = {"answer": "Main block has 40 bags of cement.", "read": "Read the stock of Cement at Main block",
         "question": 5, "opens": "/materials",
         "from": [{"sender": "Ravi", "site": "Main block", "summary": "50 bags cement came"},
                  {"sender": "Anu", "site": "Main block", "summary": "10 bags cement used"}]}
    out = effects.cards(effects.ANSWER, f, True)
    assert out["title"] == "Question" and [c["key"] for c in out["cards"]] == ["answer", "answer_read", "answer_from"]
    built = out["cards"][2]
    assert built["after"] == "2" and built["unit"] == "messages" and built["tag"] == "proof"
    # The newest first: what was said last is what moved the number last.
    assert built["sentence"] == ("From 2 messages by 2 people today. Anu: 10 bags cement used (Main block); "
                                 "Ravi: 50 bags cement came (Main block).")
    assert all(c["question"] == 5 and c["say"] for c in out["cards"])


def test_nothing_saved_today_is_said_as_earlier_days_never_as_a_count_of_zero():
    out = effects.answer_cards({"answer": None, "read": "Read today's attendance", "question": 3,
                                "opens": "/labour", "from": []}, True)
    assert [c["key"] for c in out] == ["answer_read", "answer_from"]
    assert out[-1]["title"] == "Built from earlier days" and out[-1]["after"] is None


def test_more_messages_than_it_names_are_counted():
    f = {"answer": "x", "read": "Read the day's updates", "question": 6, "opens": "/reports",
         "from": [{"sender": f"P{i}", "site": None, "summary": f"line {i}"} for i in range(5)]}
    sentence = effects.answer_cards(f, True)[-1]["sentence"]
    assert sentence.startswith("From 5 messages by 5 people today. P4: line 4; P3: line 3; P2: line 2")
    assert sentence.endswith("; and 2 earlier ones.")


# --- the read: which of today's messages count -----------------------------------------------------------------------

class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def scalar_one(self):
        return self._scalar

    def all(self):
        return self._rows


class _Conn:
    """Three reads: the day's start, the movements' materials, the names."""

    def __init__(self, materials):
        self.materials = materials

    async def execute(self, sql, params=None):
        q = str(sql)
        if "AT TIME ZONE" in q:
            return _Result(scalar=datetime.datetime(2026, 11, 13, 18, 30, tzinfo=datetime.UTC))
        if "material_receipts" in q:
            ids = set(params["r"]) | set(params["u"])
            return _Result([type("R", (), {"id": i, "material_id": m})() for i, m in self.materials.items() if i in ids])
        return _Result([type("R", (), {"id": str(S1), "name": "Main block"})(),
                        type("R", (), {"id": CEMENT, "name": "Cement"})()])


def _auth(sites=None, role="ADMIN"):
    scope = ProjectAccessScope(mode="custom_projects", project_ids={P1})
    site = SiteAccessScope(mode="all_sites", site_ids=set()) if sites is None else SiteAccessScope(
        mode="custom_sites", site_ids=set(sites))
    return AuthorizationContext(user_id=uuid.uuid4(), organization_id=ORG, role=role, status="active",
                                access_policy=AccessPolicy(mode=scope.mode, projects=[]), project_scope=scope,
                                site_scopes={P1: site})


R_CEMENT, R_STEEL, R_LATER, U_CEMENT = (str(uuid.uuid4()) for _ in range(4))
DAY = [
    _row("m1", [_saved("record_receipt", R_CEMENT, "50 bags cement came")]),
    _row("m2", [_saved("record_receipt", R_STEEL, "200 kg steel came")], sender="Anu"),        # another material
    _row("m3", [_saved("record_usage", U_CEMENT, "10 bags cement used")], site=S2, site_name="Annex"),  # other site
    _row("m4", [{"tools": ["record_receipt"], "pending": ["5 bags cement"]}]),                  # a draft, not saved
    _row("m5", [{"tools": ["record_transfer"], "saved": [{"tool": "record_transfer", "status": 201,
                                                          "summary": "5 bags moved"}]}]),     # no material record
    _row("q", [_ask(("stock_summary", {"site_id": str(S1), "material_id": CEMENT}))],
         text="How much cement is at Main block?", reply="Main block has 40 bags of cement."),
    _row("m6", [_saved("record_receipt", R_LATER, "20 bags cement came")]),                    # after the question
]


@pytest.fixture
def feed(monkeypatch):
    async def live_feed_rows(self, *, organization_id, since, until, limit=300):
        assert until - since == datetime.timedelta(days=1)
        return [dict(r) for r in DAY]

    monkeypatch.setattr("mesiri.infrastructure.postgres.repositories.fact_reviews.PostgresFactReviewRepository.live_feed",
                        live_feed_rows)


MATERIALS = {R_CEMENT: CEMENT, R_STEEL: STEEL, R_LATER: CEMENT, U_CEMENT: CEMENT}


async def test_only_todays_saved_messages_before_it_at_that_site_of_that_material_count(feed):
    f = await effects.read_answer(_Conn(MATERIALS), ORG, "q", TODAY, True, auth=_auth())
    assert f["read"] == "Read the stock of Cement at Main block" and f["question"] == 5
    assert f["answer"] == "Main block has 40 bags of cement." and f["opens"] == "/materials"
    assert f["from"] == [{"sender": "Ravi", "site": "Main block", "summary": "50 bags cement came"}]


async def test_guard_a_site_the_viewer_does_not_see_gives_none_of_its_messages(feed, monkeypatch):
    monkeypatch.setitem(DAY[0], "site_id", S2)  # the delivery is now at a site this viewer is not given
    f = await effects.read_answer(_Conn(MATERIALS), ORG, "q", TODAY, True, auth=_auth(sites=[S1]))
    assert f["from"] == []


async def test_without_a_material_the_sites_movements_all_count_transfer_too(feed, monkeypatch):
    monkeypatch.setitem(DAY[5], "turns", [_ask(("stock_summary", {"site_id": str(S1)}))])
    f = await effects.read_answer(_Conn(MATERIALS), ORG, "q", TODAY, True, auth=_auth())
    assert [m["summary"] for m in f["from"]] == ["50 bags cement came", "200 kg steel came", "5 bags moved"]
    assert f["read"] == "Read the stock at Main block"


async def test_guard_not_a_question_of_today_or_one_built_from_nothing_has_no_ripple(feed, monkeypatch):
    assert await effects.read_answer(_Conn(MATERIALS), ORG, "not-today", TODAY, True, auth=_auth()) is None
    assert await effects.read_answer(_Conn(MATERIALS), ORG, "m1", TODAY, True, auth=_auth()) is None
    monkeypatch.setitem(DAY[5], "turns", [_ask(("list_projects", {}))])
    assert await effects.read_answer(_Conn(MATERIALS), ORG, "q", TODAY, True, auth=_auth()) is None


# --- the route ----------------------------------------------------------------------------------------------------------

async def test_guard_the_route_answers_404_for_a_message_not_seen(monkeypatch):
    async def nowhere(conn, org, message_id):
        return None

    async def company(conn, org, message_id):
        return {"project_id": None, "site_id": None}

    monkeypatch.setattr(effects, "locate_message", nowhere)
    with pytest.raises(HTTPException) as err:
        await dpr_router.get_effects(kind="answer", record_id=uuid.uuid4(), auth_context=_auth(), conn=None)
    assert err.value.status_code == 404
    # A question that named no project is the company's: only for those who see every project.
    monkeypatch.setattr(effects, "locate_message", company)
    with pytest.raises(HTTPException) as err:
        await dpr_router.get_effects(kind="answer", record_id=uuid.uuid4(), auth_context=_auth(), conn=None)
    assert err.value.status_code == 404


async def test_guard_a_question_about_spending_is_not_there_for_a_role_that_does_not_see_it(feed, monkeypatch):
    monkeypatch.setitem(DAY[5], "turns", [_ask(("list_expenses", {"site_id": str(S1)}))])
    assert await effects.read_answer(_Conn(MATERIALS), ORG, "q", TODAY, False, auth=_auth()) is None
    assert (await effects.read_answer(_Conn(MATERIALS), ORG, "q", TODAY, True, auth=_auth()))["question"] == 1
