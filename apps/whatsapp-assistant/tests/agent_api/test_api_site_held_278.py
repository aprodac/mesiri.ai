"""WA-278: the code owns the draft across turns, part 1: a line is held while its site is asked.

Ilan's live test on Aprodac, 12 Nov 2026, 02:12 to 02:20 IST (tools on demand on, gemini-3.5-flash-lite):

- 02:12 "cement came, 30 masons came, make it the DPR": the cement and the masons were refused for their site
  ("Which site is this for? Nothing was prepared"), the report (it needs no site) stayed alone on the card;
- 02:13 the site tap: the model prepared only the report again; Send was tapped and the day's report went out to
  everyone with nothing recorded;
- 02:14 "update first!": both lines refused for the site again, the reply said they were updated;
- 02:14 the second site tap: the delivery came back as usage.

Root cause: a refused line was thrown away and the model was asked to prepare it again from the conversation after
the answer. Each time is a new reading, and a tap carries nothing of what it answers.

The class, held here:
- a line refused only for its site is KEPT by the code with the call the model made (``ApiTurn.site_held``);
- the site question is the code's line and the code's buttons, in the person's language;
- the answer (a tap is the site's name, or the name typed or said) makes the code prepare the kept lines itself,
  with the same tool and figures; a bare answer runs no model at all;
- a message that is not the answer drops nothing: the lines stay held and the site is asked again;
- a report is not prepared while updates wait (held for a site or on the card): they are saved first;
- the model repeating a line the code just prepared adds nothing.

Guards: with one site nothing is held or asked; a site named in the message is used at once; a report asked for
with nothing waiting is prepared as before.
"""

from __future__ import annotations

import time

from tests.agent_api import replaykit as rk

from agent_api import whatsapp as wa
from agent_api.agent import (
    HELD_FOR_SITE,
    WHICH_SITE,
    ApiAgent,
    PendingWrite,
    Places,
    is_only_a_place,
    names_a_place,
    updates_not_saved,
    which_site_line,
)
from agent_api.tools import CONFIRM_ARG, MATERIAL_SAID
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = "0431ae5c-8ced-4ffa-8edc-ef1736f1af80"
ANNEX = "d721d8d5-26ce-461c-bce0-4d86db53eab8"
MAIN = "40659b01-5a92-4517-8ce9-08b089b6ab73"
CEMENT = "3f194e81-47cb-43ec-b0e9-d2aa0a3311c8"
BAGS = "03e5cbfa-43d6-4af5-b18a-61aa7f884af7"
FACTS = (f"The person's projects and sites (use these ids):\n- project Green Villa (project_id {PROJECT})\n"
         f"  - site Annex (site_id {ANNEX})\n  - site Main block (site_id {MAIN})\n\n"
         f"Units (unit_id): bags ({BAGS})\nMaterials (material_id, default unit):\n- Cement ({CEMENT}, bags)")
PLACES = Places(sites=[(ANNEX, "Annex", PROJECT), (MAIN, "Main block", PROJECT)], projects=[(PROJECT, "Green Villa")])
ONE_SITE = Places(sites=[(ANNEX, "Annex", PROJECT)], projects=[(PROJECT, "Green Villa")])

CEMENT_CAME = ("record_receipt", {"project_id": PROJECT, "site_id": ANNEX, "material_id": CEMENT, "unit_id": BAGS,
                                  "quantity": 50, "occurred_date": "2026-11-11", MATERIAL_SAID: "cement",
                                  CONFIRM_ARG: "50 bags cement"})
MASONS = ("record_attendance", {"project_id": PROJECT, "site_id": ANNEX, "occurred_date": "2026-11-11",
                                "lines": [{"trade": "Mason", "headcount": 30}], CONFIRM_ARG: "30 masons"})
SEND = ("send_dpr", {"project_id": PROJECT, CONFIRM_ARG: "Send DPR, Green Villa"})


class Counting(FakeToolCallingProvider):
    def __init__(self, script: list) -> None:
        super().__init__(script)
        self.prompts: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.prompts.append(system_prompt)
        return await super().run_tools(system_prompt, messages, tools, handler, **kwargs)


async def _run(script: list, text: str, places: Places = PLACES, **kwargs):  # noqa: ANN003, ANN202
    model = Counting(script)
    api = rk.RecordedApi(catalogue=rk.facts_catalogue(FACTS))
    turn = await ApiAgent(model, rk._real_tools()).run(  # type: ignore[arg-type]
        api, text, facts=FACTS, places=places, language="manglish", **kwargs)
    return turn, model


# --- the first message: nothing is thrown away -----------------------------------------------------------------------

async def test_lines_refused_for_the_site_are_kept_with_their_calls() -> None:
    turn, _ = await _run([[CEMENT_CAME, MASONS], "Sheri."], "50 chaakku cement vannu, 30 mason vannu")
    assert turn.pending == []
    assert [h["tool"] for h in turn.site_held] == ["record_receipt", "record_attendance"]
    assert turn.site_held[0]["arguments"]["quantity"] == 50
    assert HELD_FOR_SITE in str(turn.calls[0]["result"]) and "error" not in turn.calls[0]["result"]


async def test_the_site_question_is_the_codes_line_and_buttons() -> None:
    turn, _ = await _run([[CEMENT_CAME], "Cement update cheythu, site ethaanu ennu parayoo?"], "50 chaakku cement vannu")
    assert turn.question == which_site_line("manglish") == "Ithu ethu site-il aanu?"
    assert turn.options == ["Annex", "Main block"]
    assert turn.reply == turn.question  # the model's "update cheythu" never goes out
    assert which_site_line("english") == WHICH_SITE and which_site_line(None) == WHICH_SITE


async def test_the_same_line_called_twice_is_held_once() -> None:
    turn, _ = await _run([[CEMENT_CAME, CEMENT_CAME], "Sheri."], "50 chaakku cement vannu")
    assert len(turn.site_held) == 1


# --- the answer: the code prepares the kept lines, the model is not asked ---------------------------------------------

async def test_a_bare_site_answer_prepares_the_held_lines_with_no_model() -> None:
    first, _ = await _run([[CEMENT_CAME, MASONS], "Sheri."], "50 chaakku cement vannu, 30 mason vannu")
    turn, model = await _run(["this must never be read"], "Annex", site_held=first.site_held)
    assert model.calls == 0  # no model run for a tap
    assert [e.tool for e in turn.pending] == ["record_receipt", "record_attendance"]  # a delivery stays a delivery
    assert turn.pending[0].body["site_id"] == ANNEX and turn.pending[0].body["quantity"] == 50
    assert turn.pending[1].body["site_id"] == ANNEX
    assert turn.site_held == [] and turn.question == "" and turn.reply == ""
    assert [c["tool"] for c in turn.calls] == ["record_receipt", "record_attendance"]  # in the trace, as the code's


async def test_the_site_said_with_more_words_runs_the_model_told_what_the_code_did() -> None:
    first, _ = await _run([[CEMENT_CAME], "Sheri."], "50 chaakku cement vannu")
    turn, model = await _run([[CEMENT_CAME], "Sheri."], "Annex-il aanu bro, pinne innu mazha undayirunnu",
                             site_held=first.site_held)
    assert model.calls >= 1 and "The CODE already prepared these" in model.prompts[0]
    assert [e.tool for e in turn.pending] == ["record_receipt"]  # the model's own copy of the line is not added


async def test_a_message_that_is_not_the_answer_keeps_the_lines_and_asks_again() -> None:
    first, _ = await _run([[CEMENT_CAME], "Sheri."], "50 chaakku cement vannu")
    turn, _ = await _run(["Njan Mesiri aanu."], "nee ethu model aanu?", site_held=first.site_held)
    assert turn.site_held == first.site_held
    assert turn.options == ["Annex", "Main block"] and turn.question == "Ithu ethu site-il aanu?"
    assert turn.pending == []


# --- the report waits for the updates ---------------------------------------------------------------------------------

async def test_a_report_is_not_prepared_beside_lines_held_for_their_site() -> None:
    turn, _ = await _run([[CEMENT_CAME, MASONS, SEND], "Sheri."], "cement vannu, 30 mason vannu, DPR ayakku")
    assert turn.pending == []  # 12 Nov 02:13: the report was the only thing on the card, and it was sent
    assert "updates first" in str(turn.calls[2]["result"])
    assert len(turn.site_held) == 2


async def test_a_report_is_not_prepared_while_updates_wait_on_the_card() -> None:
    waiting = PendingWrite(tool="record_receipt", method="POST", path="/materials/inflows", params={},
                           body={"site_id": ANNEX, "project_id": PROJECT}, summary="50 bags cement, Annex",
                           idempotency_key="k1")
    turn, _ = await _run([[SEND], "Save cheythittu report ayakkaam."], "DPR ayakku", ready=[waiting])
    assert [e.tool for e in turn.pending] == ["record_receipt"]


async def test_a_report_with_nothing_waiting_is_prepared_as_before() -> None:
    turn, _ = await _run([[SEND], "Sheri."], "innathe DPR ayakku")
    assert [e.tool for e in turn.pending] == ["send_dpr"]


def test_updates_not_saved_counts_held_and_site_lines_only() -> None:
    tools = rk._real_tools()
    delivery = PendingWrite(tool="record_receipt", method="POST", path="/materials/inflows", params={}, body={},
                            summary="x", idempotency_key="a")
    report = PendingWrite(tool="send_dpr", method="POST", path="/dpr/projects/p/send", params={}, body={},
                          summary="y", idempotency_key="b")
    project = PendingWrite(tool="create_project", method="POST", path="/projects", params={}, body={"name": "H"},
                           summary="z", idempotency_key="c")
    assert updates_not_saved([{"tool": "record_work"}], [delivery, report, project], tools) == 2
    assert updates_not_saved([], [report, project], tools) == 0


# --- guards -----------------------------------------------------------------------------------------------------------

async def test_one_site_holds_and_asks_nothing() -> None:
    turn, _ = await _run([[CEMENT_CAME], "Sheri."], "50 chaakku cement vannu", places=ONE_SITE)
    assert [e.tool for e in turn.pending] == ["record_receipt"] and turn.site_held == [] and turn.options == []


async def test_a_site_named_in_the_message_is_used_at_once() -> None:
    turn, _ = await _run([[CEMENT_CAME], "Sheri."], "Main block-il 50 chaakku cement vannu")
    assert turn.pending[0].body["site_id"] == MAIN and turn.site_held == []


def test_what_counts_as_the_site_answer() -> None:
    assert names_a_place("Annex", PLACES) and names_a_place("annex-il aanu", PLACES)
    assert not names_a_place("Other", PLACES) and not names_a_place("50 chaakku cement vannu", PLACES)
    assert is_only_a_place("Annex", PLACES) and is_only_a_place(" main  block ", PLACES)
    assert not is_only_a_place("Annex-il aanu bro", PLACES) and not is_only_a_place("Annex", None)


# --- the chat keeps them ----------------------------------------------------------------------------------------------

def test_the_chat_keeps_held_lines_for_half_an_hour() -> None:
    now = time.time()
    lines = [{"tool": "record_receipt", "arguments": {"quantity": 50}}]
    assert wa._site_held({"site_held": {"lines": lines, "at": now - 60}}, now) == lines
    assert wa._site_held({"site_held": {"lines": lines, "at": now - wa.SITE_HELD_SECONDS - 1}}, now) == []
    assert wa._site_held({}, now) == []
    assert wa._site_held({"site_held": {"lines": [{"arguments": {}}], "at": now}}, now) == []  # no tool: not a line

