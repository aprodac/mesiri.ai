"""[248] (5 Nov 08:16, New India, a new owner's first voice note, cor_20da685a6ebf4f3082b98f31fb719bb5): Mesiri asked
the person to say "cement" in English. Translating is the AI's job, never the person's.

The code now translates itself: a material word in another script ("സിമൻ്റ്") goes through the provider's translation
route and is matched in English to the listed record; a free-text body field still in another script is translated
in place before the line is held. Only what it cannot translate goes back to the model, once; after that the line is
held as it is. No reply, no tool error, ever tells the person to say a word in English.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.agent_api.standin import ACTOR
from tests.agent_api.test_api_english_bodies_243 import (
    CATALOG,
    CEMENT,
    UNIT,
    _materials_api,
    _receipt,
)

from agent_api.agent import ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.fill import field_at, set_field, to_english, translate_body
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import TranslationResult

WORDS = {"സിമൻ്റ്": "Cement", "സിമന്റ്": "cement", "പ്രൈമർ": "Primer", "മേസൺ": "mason",
         "പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു": "Plastering done"}


class Translating(FakeToolCallingProvider):
    """The scripted model plus the provider's translation route (the control panel's "translation" row)."""

    def __init__(self, script: list, words: dict[str, str] | None = None, *, fail: bool = False) -> None:
        super().__init__(script)
        self.words = WORDS if words is None else words
        self.fail = fail
        self.translated: list[str] = []

    async def translate_to_english(self, text: str, *, correlation_id: str | None = None) -> TranslationResult:
        self.translated.append(text)
        if self.fail:
            raise RuntimeError("translation down")
        return TranslationResult(translated_text=self.words.get(text, text))


async def _run(provider, text: str, catalog: list | None = None):  # noqa: ANN001, ANN202
    saved: list = []
    if catalog is not None:
        CATALOG[:] = catalog
    app = _materials_api(saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("record_receipt", "add_material")))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(provider, tools).run(client, text, language="malayalam", channel="whatsapp_voice")
        results = await confirm(client, turn.pending) if turn.pending else []
        return turn, saved, results
    finally:
        CATALOG[:] = [{"id": CEMENT, "name": "Cement", "aliases": []}]
        await client.close()


def _no_ask_in_english(turn) -> None:  # noqa: ANN001
    told = " ".join([turn.reply, *(str(c.get("result")) for c in turn.calls)])
    assert not re.search(r"ask the person[^.]*english|what it is called in english", told, re.I), told


# -- the reported case -------------------------------------------------------------------------------------------


async def test_malayalam_cement_is_translated_by_mesiri_and_held_on_the_listed_cement_in_one_model_step() -> None:
    model = Translating([[_receipt("സിമൻ്റ്")], "റെഡി."])
    turn, saved, results = await _run(model, "20 ചാക്ക് സിമൻ്റ് വന്നു")
    assert "error" not in turn.calls[0]["result"]  # held on the first call: no round trip back to the model
    assert "സിമൻ്റ്" in model.translated
    assert [e.tool for e in turn.pending] == ["record_receipt"] and all(r.ok for r in results)
    assert saved == [("receipt", CEMENT, 20.0)]
    _no_ask_in_english(turn)


async def test_translation_down_the_models_own_pick_stands_never_the_person() -> None:
    turn, saved, _ = await _run(Translating([[_receipt("സിമൻ്റ്")], "റെഡി."], fail=True), "20 ചാക്ക് സിമൻ്റ് വന്നു")
    assert saved == [("receipt", CEMENT, 20.0)]
    _no_ask_in_english(turn)


# -- siblings -----------------------------------------------------------------------------------------------------


async def test_sibling_a_translated_word_for_another_material_is_never_recorded_as_the_near_one() -> None:
    # "പ്രൈമർ" translates to Primer; the model picked Paint: never saved as Paint ([210] still holds).
    paint = "7f1c0a9e-0000-4000-8000-000000000001"
    model = Translating([[_receipt("പ്രൈമർ", paint)], "ശരി."])
    turn, saved, _ = await _run(model, "20 drum പ്രൈമർ വന്നു",
                                catalog=[{"id": paint, "name": "Paint", "aliases": []}])
    assert ("receipt", paint, 20.0) not in saved
    assert "Primer" in str(turn.calls[0]["result"])  # held as a new material in English, never Malayalam
    _no_ask_in_english(turn)


async def test_sibling_a_new_material_said_in_malayalam_is_translated_and_found_already_listed() -> None:
    add = ("add_material", {"name": "സിമന്റ്", CONFIRM_ARG: "പുതിയ: സിമന്റ്"})
    turn, saved, _ = await _run(Translating([[add], [_receipt("cement")], "റെഡി."]), "സിമന്റ് 20 ചാക്ക്")
    assert "already in the company's list" in turn.calls[0]["result"]["error"]
    assert saved == [("receipt", CEMENT, 20.0)]  # never a second Cement


async def test_sibling_free_text_fields_are_translated_in_place_nested_too() -> None:
    params = {"properties": {"narrative": {"type": "string"},
                             "lines": {"type": "array", "items": {"properties": {"trade": {"type": "string"}}}}}}
    body = {"narrative": "പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു", "lines": [{"trade": "mason"}, {"trade": "മേസൺ"}]}
    assert await translate_body(Translating([]), params, body) == []
    assert body == {"narrative": "Plastering done", "lines": [{"trade": "mason"}, {"trade": "mason"}]}


async def test_untranslatable_text_is_left_out_and_paths_are_safe() -> None:
    assert await to_english(Translating([], {"ശരി": "ശരി"}), ["ശരി"]) == {}  # still not Latin: not a translation
    assert await to_english(FakeToolCallingProvider([]), ["സിമൻ്റ്"]) == {}  # no translation route
    body = {"lines": [{"trade": "x"}]}
    set_field(body, "lines[5].trade", "y")
    set_field(body, "nothing.here", "y")
    assert body == {"lines": [{"trade": "x"}]} and field_at(body, "lines[1].trade") == "x"


# -- guards -------------------------------------------------------------------------------------------------------


async def test_guard_english_never_goes_through_translation() -> None:
    model = Translating([[_receipt("cement")], "Ready."])
    _, saved, _ = await _run(model, "20 bags cement came")
    assert model.translated == [] and saved == [("receipt", CEMENT, 20.0)]


async def test_guard_a_listed_malayalam_alias_matches_without_translation() -> None:
    model = Translating([[_receipt("സിമൻ്റ്")], "റെഡി."])
    _, saved, _ = await _run(model, "20 ചാക്ക് സിമൻ്റ്", catalog=[{"id": CEMENT, "name": "Cement", "aliases": ["സിമൻ്റ്"]}])
    assert model.translated == [] and saved == [("receipt", CEMENT, 20.0)]


def test_guard_nothing_tells_the_model_to_ask_the_person_for_english() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "agent_api"
    for name in ("agent.py", "materials.py", "SOP.md"):
        text = (src / name).read_text(encoding="utf-8")
        assert not re.search(r"Ask the person[^.\n]*English", text), name


def test_the_sop_answers_construction_questions_and_never_makes_up_a_quantity() -> None:
    sop = " ".join((Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8").split())
    assert "experienced construction engineer" in sop
    assert "is a question: answer it and prepare nothing" in sop
    assert "Never make up a quantity" in sop
    assert "Translating is your job" in sop
    assert CONFIRM_ARG and UNIT  # shared fixtures stay importable
