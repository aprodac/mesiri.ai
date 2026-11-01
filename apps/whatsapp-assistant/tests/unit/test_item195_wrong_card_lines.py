"""Item 195: five wrong card lines of the 1 Nov live re-test (swap ignored, invented tons,
weather as an issue, a dropped count, a stray "Couldn't read")."""

from __future__ import annotations

from runtime.agent import reroute
from runtime.agent.cards import merge_changes
from runtime.agent.toolbox import unsaid_zero_count
from runtime.agent.tools import REPORT_ISSUE, SET_SITE_CONDITIONS
from runtime.agent.wording import say
from runtime.material_units import fit_stock_unit
from runtime.unit_words import unit_the_sender_gave


def test_swapped_material_drops_the_old_english_name():  # bug 1
    args = {"material": "TMT steel bars", "name_en": "TMT steel bars", "quantity": 50, "unit": "nos"}
    merged = merge_changes("save_material_receipt", args, {"material": "12mm steel rod"})
    assert merged["material"] == "12mm steel rod" and "name_en" not in merged and merged["quantity"] == 50
    kept = merge_changes("save_material_receipt", args, {"quantity": 40})
    assert kept["name_en"] == "TMT steel bars"  # guard: a figure change keeps the name


def test_a_count_is_never_given_a_unit_the_sender_did_not_say():  # bug 2
    assert unit_the_sender_gave("tons", 50, "TMT steel bar 50 ennam vannu") == "nos"
    assert unit_the_sender_gave("kg", 200, "200 bricks 200 nos") == "nos"
    assert unit_the_sender_gave("tons", 2, "2 tons TMT vannu") is None  # said: kept
    assert unit_the_sender_gave("bags", 30, "30 chakk cement") is None  # not a count


NOS = {"id": "u-nos", "code": "nos"}
TONS = {"id": "u-tons", "code": "tons"}


class _Catalog:
    async def resolve_unit(self, text):  # noqa: ANN001, ANN201
        return NOS

    async def get_unit(self, unit_id):  # noqa: ANN001, ANN201
        return TONS

    async def find_conversion(self, **_kw):  # noqa: ANN003, ANN201
        return 20  # a saved company conversion must not turn a count into tons


async def test_nos_of_a_ton_stocked_material_stays_nos():  # bug 2
    fields = {"quantity": 50, "unit": "nos"}
    fit = await fit_stock_unit(
        fields, {"id": "m", "name": "TMT", "default_unit_id": "u-tons"}, catalog_query=_Catalog(), organization_id="o"
    )
    assert fit.kind == "ok" and fields["quantity"] == 50 and fields["unit"] == "nos"


def test_weather_without_damage_is_the_days_conditions():  # bug 3
    said = "innu mazha karanam pani kuravaayirunnu"
    redirect = reroute.before(REPORT_ISSUE, {"issue_type": "WEATHER"}, said)
    assert redirect is not None and redirect.tool == SET_SITE_CONDITIONS
    assert redirect.args == {"weather": "rainy"}
    # work that stopped for hours is a blocker: still an issue (request 104), and so is a
    # message that names no weather at all
    assert reroute.before(REPORT_ISSUE, {"issue_type": "WEATHER"}, "rain since 2 pm, work stopped") is None
    assert reroute.before(REPORT_ISSUE, {"issue_type": "WEATHER", "delay_duration_minutes": 120}, "mazha") is None
    assert reroute.before(REPORT_ISSUE, {"issue_type": "WEATHER"}, "power cut, no work today") is None


def test_damage_with_the_weather_is_still_an_issue():  # bug 3 guard
    assert reroute.before(REPORT_ISSUE, {"issue_type": "WEATHER"}, "mazha karanam wall veenu") is None
    assert reroute.before(REPORT_ISSUE, {"issue_type": "SAFETY"}, "worker fell") is None


def test_refusal_line_never_says_got_it_or_nothing_saved():  # bug 1 / 5
    for language in ("english", "manglish", "malayalam", "hindi", "hinglish"):
        line = say("change.refused", language)
        assert "Got it" not in line
        card = say("material_request.not_built_card", language)
        assert "nothing was saved" not in card.casefold() and "onnum save cheythilla" not in card


def test_a_finish_is_still_not_a_zero_count():  # bug 5 guard
    assert unsaid_zero_count("cement stock kazhinjittundu, nale venam", {"material": "cement", "counted": 0})
