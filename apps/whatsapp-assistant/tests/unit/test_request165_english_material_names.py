"""Request 165 (replaces 163): a material is always SAVED in English; Malayalam words
find the listed material; "it's new" has a way out."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.agent.material_entry import Ready, Say, add_new_label, typed_new_material_answer
from runtime.agent.material_names import english_name, transliterate

from .test_material_entry import (
    CEMENT,
    SAND,
    USR,
    _Catalog,
    _entry,
    _Modules,
    _prepare,
)

MSAND = {"id": "88888888-8888-4888-8888-888888888888", "name": "M sand", "default_unit_id": "u-cum", "is_active": True}
LATERITE = {"id": "99999999-9999-4999-8999-999999999999", "name": "Laterite stone", "default_unit_id": "u-bag", "is_active": True}
CAN_ADD = _Modules(["materials"], create_roles=["SITE_ENGINEER"])


class _AliasCatalog(_Catalog):
    def __init__(self, materials: list[dict]) -> None:
        super().__init__(materials)
        self.aliases: dict[str, dict] = {}
        self.added: list[tuple] = []

    async def create_material(self, **kwargs: Any) -> dict:
        made = await super().create_material(**kwargs)
        self.materials.append(made)
        return made

    async def find_by_alias(self, *, organization_id: str, alias: str) -> dict | None:
        from mesiri.domains.materials.names import alias_key

        return self.aliases.get(alias_key(alias))

    async def add_alias(self, *, organization_id: str, material_id: str, alias: str, created_by: str | None) -> None:
        from mesiri.domains.materials.names import alias_key

        material = next(m for m in self.materials if m["id"] == material_id)
        self.aliases[alias_key(alias)] = material
        self.added.append((material["name"], alias))

    async def closest_materials(self, *, organization_id: str, name: str, limit: int = 9):
        return self.materials[:limit], len(self.materials)


def _entry_with(catalog: _Catalog):
    return _entry(catalog=catalog, modules=CAN_ADD)


@pytest.mark.parametrize(
    ("said", "english"),
    [("ചെങ്കല്ല്", "Laterite stone"), ("കല്ല്", "Stone"), ("സിമൻറ്", "Cement"), ("സിമന്റ്", "Cement"),
     ("എംസാന്റ്", "M sand"), ("ഇഷ്ടിക", "Bricks"), ("kambi", "TMT steel bars"), ("siment", "Cement"),
     ("chenkallu", "Laterite stone")],
)
def test_local_words_have_an_english_name(said, english):
    named = english_name(said)
    assert (named.name, named.sure) == (english, True)


def test_laterite_and_stone_are_different_materials():
    assert english_name("ചെങ്കല്ല്").name != english_name("കല്ല്").name


def test_the_models_latin_name_is_used_and_a_malayalam_one_falls_back_to_transliteration():
    assert english_name("പാറ", "rubble stone").name == "Rubble stone"
    bad = english_name("പാറ", "പാറ")
    assert not bad.sure and bad.name == "Paara"
    assert english_name("ചെങ്കല്ല്").said == "ചെങ്കല്ല്"
    assert transliterate("ഇഷ്ടിക") == "ishtika"


def test_english_names_are_unchanged():
    named = english_name("TMT steel bars")
    assert (named.name, named.sure) == ("TMT steel bars", True)


async def test_malayalam_cement_and_m_sand_match_the_listed_materials():
    catalog = _AliasCatalog([CEMENT, SAND, MSAND])
    for said, expected in (("സിമന്റ്", "Cement"), ("സിമൻറ്", "Cement"), ("എംസാന്റ്", "M sand")):
        ready = await _prepare(_entry_with(catalog), material_name=said, unit="cum" if expected == "M sand" else "bags")
        assert isinstance(ready, Ready), said  # no "add as new"
        assert ready.event.fields["material_name"] == expected


async def test_a_new_malayalam_material_is_offered_and_saved_in_english_with_the_word_as_alias():
    catalog = _AliasCatalog([CEMENT, SAND])
    entry = _entry_with(catalog)
    said = await _prepare(entry, material_name="ചെങ്കല്ല്", name_en="Laterite stone", unit="bags")
    assert isinstance(said, Say)
    assert said.options[0].startswith("➕ Add Laterite stone")
    assert "ചെങ്കല്ല്" in said.question and 'saved as "Laterite stone"' in said.question
    ready = await _prepare(entry, material_name="ചെങ്കല്ല്", name_en="Laterite stone", unit="bags", new_material=True)
    assert isinstance(ready, Ready)
    assert catalog.created == [("Laterite stone", "u-bag", USR)]
    assert catalog.added == [("Laterite stone", "ചെങ്കല്ല്")]
    assert ready.event.fields["material_name"] == "Laterite stone"
    assert "name_en" not in ready.event.fields
    # the next message with the word, or its Manglish, matches with no question
    for word in ("ചെങ്കല്ല്", "chenkallu"):
        again = await _prepare(_entry_with(catalog), material_name=word, unit="bags")
        assert isinstance(again, Ready) and again.event.fields["material_name"] == "Laterite stone"


async def test_the_table_name_needs_no_model_help():
    catalog = _AliasCatalog([CEMENT])
    ready = await _prepare(_entry_with(catalog), material_name="ചെങ്കല്ല്", unit="bags", new_material=True)
    assert isinstance(ready, Ready) and catalog.created[0][0] == "Laterite stone"


async def test_a_model_name_in_malayalam_falls_back_to_transliteration_and_asks():
    catalog = _AliasCatalog([CEMENT])
    said = await _prepare(_entry_with(catalog), material_name="പാറ", name_en="പാറ", unit="bags")
    assert isinstance(said, Say)
    assert 'Name it "Paara"? Or type the English name.' in said.question
    assert said.options[0].startswith("➕ Add Paara")
    ready = await _prepare(_entry_with(catalog), material_name="പാറ", name_en="പാറ", unit="bags", new_material=True)
    assert isinstance(ready, Ready) and catalog.created[-1][0] == "Paara"
    assert catalog.created and all(c[0].isascii() for c in catalog.created)


async def test_stone_is_new_beside_laterite_and_never_merged():
    catalog = _AliasCatalog([CEMENT, LATERITE])
    entry = _entry_with(catalog)
    said = await _prepare(entry, material_name="കല്ല്", unit="bags")
    assert isinstance(said, Say)
    assert any("Add Stone" in o for o in said.options)  # a way out beside the close matches
    ready = await _prepare(entry, material_name="കല്ല്", unit="bags", new_material=True)
    assert isinstance(ready, Ready) and ready.event.fields["material_name"] == "Stone"
    assert catalog.added == [("Stone", "കല്ല്")]


def test_the_add_button_shows_the_word_in_brackets_when_it_fits():
    assert add_new_label("Stone", "കല്ല്") == "➕ Add Stone (കല്ല്)"
    assert add_new_label("Laterite stone", "ചെങ്കല്ല്").startswith("➕ Add Laterite stone")
    assert add_new_label("Cement") == "➕ Add Cement"


@pytest.mark.parametrize(
    "text", ["new", "puthiya", "it's new", "vere type", "save it as just കല്ല്", "add കല്ല്", "അല്ല, പുതിയത്"]
)
def test_a_typed_new_answer_picks_the_add_option(text):
    options = ["Laterite stone", add_new_label("Stone", "കല്ല്")]
    assert typed_new_material_answer(text, "കല്ല്", options) == options[1]


def test_typing_a_listed_name_still_picks_it():
    options = ["Laterite stone", add_new_label("Stone", "കല്ല്")]
    assert typed_new_material_answer("laterite stone", "കല്ല്", options) == "Laterite stone"
