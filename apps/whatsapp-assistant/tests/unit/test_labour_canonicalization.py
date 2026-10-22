"""Labour canonicalization — turning whatever the AI returned into `lines`.

This is the seam the whole Labour workflow depends on: `workflows/labour_update`
reads exactly one field, `lines`, where each entry is either a named person or
an anonymous headcount group (Labour plan principle P10). Everything an
extraction provider might plausibly hand back has to arrive in that one shape,
because the alternative is teaching the graph three input dialects.

Kept separate from test_canonicalization.py, which is already long and covers
the material/finance aliasing.
"""

from __future__ import annotations

import pytest

from mesiri_contracts.assistant.context_enums import ContextConfidence, ContextSource
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"


def _context() -> ResolvedContextV2:
    return ResolvedContextV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        context_organization_id="org_1",
        context_user_id="usr_1",
        context_project_id="prj_1",
        context_site_id="site_1",
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        context_source=ContextSource.USER_DEFAULT,
        context_confidence=ContextConfidence.HIGH,
    )


def _event(fields: dict, *, modality: InputModality = InputModality.TEXT, media: str | None = None):
    """The labour fields as the agent's labour entry builds them (ARCH-06:
    runtime/agent/labour_entry.py runs this same normaliser)."""
    from types import SimpleNamespace

    from canonicalization.builder import _normalize_labour_fields

    out = _normalize_labour_fields(dict(fields), input_modality=modality)
    if media:
        out["media_object_key"] = media
    return SimpleNamespace(fields=out)


def _lines(fields: dict) -> list[dict]:
    return _event(fields).fields["lines"]


# --- the shape the extraction prompt now asks for -------------------------


def test_named_workers_become_one_line_each():
    lines = _lines(
        {
            "workers": [
                {"name": "Ravi", "trade": "mason", "headcount": 1},
                {"name": "Arun", "trade": "painter", "headcount": 1},
            ]
        }
    )
    assert [line["worker_name"] for line in lines] == ["Ravi", "Arun"]
    assert [line["trade"] for line in lines] == ["mason", "painter"]
    assert [line["headcount"] for line in lines] == [1, 1]


def test_headcount_groups_carry_no_name():
    lines = _lines({"workers": [{"trade": "helper", "headcount": 12}]})
    assert lines[0]["worker_name"] is None
    assert lines[0]["headcount"] == 12


def test_named_and_headcount_lines_mix_in_one_report():
    """P10: "Ravi mason, Arun painter, 12 helpers, 4 carpenters" is one
    message, not two modes."""
    lines = _lines(
        {
            "workers": [
                {"name": "Ravi", "trade": "mason", "headcount": 1},
                {"name": "Arun", "trade": "painter", "headcount": 1},
                {"trade": "helper", "headcount": 12},
                {"trade": "carpenter", "headcount": 4},
            ]
        }
    )
    assert len(lines) == 4
    assert sum(line["headcount"] for line in lines) == 18
    assert [bool(line["worker_name"]) for line in lines] == [True, True, False, False]


def test_wage_is_carried_when_stated():
    lines = _lines({"workers": [{"name": "Ravi", "trade": "mason", "daily_wage": 800}]})
    assert lines[0]["daily_wage"] == 800


def test_wage_is_absent_when_not_stated():
    """P9: a wage-less report is a legitimate fast capture, not an error, and
    must not be filled in with a guess."""
    assert "daily_wage" not in _lines({"workers": [{"trade": "helper", "headcount": 6}]})[0]


# --- defending against what providers actually do -------------------------


def test_a_named_worker_is_always_one_person():
    """The dangerous misread: a provider that folds "Ravi" and "12 helpers"
    into `{"name": "Ravi", "headcount": 12}` would otherwise bill twelve days
    to one man. A name pins the count to 1."""
    assert _lines({"workers": [{"name": "Ravi", "headcount": 12}]})[0]["headcount"] == 1


def test_provider_key_aliases_are_accepted():
    lines = _lines({"workers": [{"worker_name": "Ravi", "role": "mason", "count": 1}]})
    assert lines[0]["worker_name"] == "Ravi"
    assert lines[0]["trade"] == "mason"


def test_bare_strings_are_kept_as_names_not_discarded():
    """Losing the only thing the user said is worse than an imperfect line."""
    lines = _lines({"workers": ["Ravi", "Arun"]})
    assert [line["worker_name"] for line in lines] == ["Ravi", "Arun"]


def test_empty_and_malformed_entries_are_skipped():
    lines = _lines({"workers": [{}, None, {"trade": "mason", "headcount": 3}]})
    assert len(lines) == 1
    assert lines[0]["trade"] == "mason"


def test_zero_or_junk_headcount_falls_back_to_one():
    assert _lines({"workers": [{"trade": "mason", "headcount": 0}]})[0]["headcount"] == 1
    assert _lines({"workers": [{"trade": "mason", "headcount": "many"}]})[0]["headcount"] == 1


def test_decimal_headcount_is_truncated_not_rejected():
    assert _lines({"workers": [{"trade": "helper", "headcount": 12.0}]})[0]["headcount"] == 12


# --- the older flat shape still works -------------------------------------




def test_already_canonical_lines_pass_through():
    """A corrected or replayed event arrives already in the final shape."""
    lines = _lines({"lines": [{"worker_name": "Ravi", "trade": "mason", "headcount": 1}]})
    assert lines[0]["worker_name"] == "Ravi"


# --- fields that must not leak into the confirmation ----------------------


def test_folded_flat_fields_do_not_also_survive_as_their_own_fields():
    """Leaving `headcount` beside the line it produced would show the same
    attendance twice in the confirmation text -- the bug
    _normalize_material_fields' alias-popping already guards against."""
    fields = _event({"headcount": 12, "trade": "helper"}).fields
    assert "headcount" not in fields
    assert "trade" not in fields
    assert "workers" not in fields


def test_report_level_contractor_is_pushed_down_to_each_line():
    """Stated once ("all from Kumar Team") but scored per worker by matching."""
    lines = _lines(
        {
            "contractor": "Kumar Team",
            "workers": [{"name": "Ravi", "trade": "mason"}, {"trade": "helper", "headcount": 5}],
        }
    )
    assert all(line["contractor"] == "Kumar Team" for line in lines)


def test_a_lines_own_contractor_wins_over_the_report_level_one():
    lines = _lines(
        {
            "contractor": "Kumar Team",
            "workers": [{"name": "Ravi", "contractor": "Self"}],
        }
    )
    assert lines[0]["contractor"] == "Self"


# --- routing and completeness ---------------------------------------------






# --- text, voice and image all land in the same place ---------------------


def test_voice_and_image_produce_the_same_structure_as_text():
    """Definition-of-Done criterion 3: one structured result regardless of how
    the report arrived. Understanding transcribes voice and reads images
    upstream; by this point all three are the same extracted fields, and this
    pins that canonicalization adds no modality-specific behaviour."""
    fields = {"workers": [{"name": "Ravi", "trade": "mason", "headcount": 1}]}
    text = _event(fields, modality=InputModality.TEXT).fields["lines"]
    voice = _event(fields, modality=InputModality.VOICE).fields["lines"]
    image = _event(fields, modality=InputModality.IMAGE).fields["lines"]
    assert text == voice == image




# --- non-Latin scripts (Malayalam, Hindi, Tamil) --------------------------


def test_a_transliterated_name_keeps_the_original_spelling():
    """Names transliterate, they never translate -- a name is a person, not
    vocabulary. The original is kept so a wrong reading stays checkable
    against the paper sheet."""
    lines = _lines(
        {"workers": [{"name": "Ravi", "name_original": "രവി", "trade": "mason", "headcount": 1}]}
    )
    assert lines[0]["worker_name"] == "Ravi"
    assert lines[0]["worker_name_original"] == "രവി"


def test_latin_script_sheets_gain_no_extra_field():
    """No noise on the common case."""
    assert "worker_name_original" not in _lines({"workers": [{"name": "Ravi", "trade": "mason"}]})[0]


def test_an_original_identical_to_the_name_is_dropped():
    lines = _lines({"workers": [{"name": "Ravi", "name_original": "Ravi", "trade": "mason"}]})
    assert "worker_name_original" not in lines[0]


def test_the_alternative_original_key_is_accepted():
    lines = _lines({"workers": [{"name": "Suresh", "original_name": "സുരേഷ്"}]})
    assert lines[0]["worker_name_original"] == "സുരേഷ്"


def test_a_transliterated_group_row_still_carries_its_english_trade():
    """Trades DO translate: കൊത്തുപണിക്കാരൻ is genuinely "mason"."""
    lines = _lines({"workers": [{"trade": "mason", "headcount": 6}]})
    assert lines[0]["trade"] == "mason"
    assert lines[0]["worker_name"] is None


# --- recorded_via: how the report reached Mesiri --------------------------


def test_a_text_report_is_recorded_via_whatsapp_text():
    event = _event({"workers": [{"name": "Ravi", "trade": "mason"}]}, modality=InputModality.TEXT)
    assert event.fields["recorded_via"] == "whatsapp_text"


def test_a_voice_report_is_recorded_via_whatsapp_voice():
    event = _event({"workers": [{"name": "Ravi", "trade": "mason"}]}, modality=InputModality.VOICE)
    assert event.fields["recorded_via"] == "whatsapp_voice"


def test_an_image_report_is_recorded_via_whatsapp_image():
    event = _event({"workers": [{"name": "Ravi", "trade": "mason"}]}, modality=InputModality.IMAGE)
    assert event.fields["recorded_via"] == "whatsapp_image"


def test_a_tapped_interactive_reply_still_counts_as_whatsapp_text():
    event = _event({"workers": [{"name": "Ravi", "trade": "mason"}]}, modality=InputModality.INTERACTIVE)
    assert event.fields["recorded_via"] == "whatsapp_text"


def test_recorded_via_reaches_the_command_mapper():
    """Display suppression is workflows/labour_update/nodes.py's job (see
    test_labour_update_nodes.py); this only pins that canonicalization
    doesn't drop the value before the mapper ever sees it."""
    event = _event({"workers": [{"name": "Ravi", "trade": "mason"}]}, modality=InputModality.VOICE)
    assert event.fields["recorded_via"] == "whatsapp_voice"


# --- dating the report ------------------------------------------------------








# ---------------------------------------------------------------------------
# Non-Latin names (Phase 4)
# ---------------------------------------------------------------------------

#: "Ravi" in Malayalam script -- the single most common case on these sites.
MALAYALAM_RAVI = "\u0d30\u0d35\u0d3f"


def test_the_native_spelling_is_kept_when_the_model_transliterates():
    """The intended path: "Ravi" is what matches the register, and the native
    spelling is what the supervisor recognises when checking the preview."""
    from canonicalization.builder import _labour_line

    line = _labour_line(
        {"name": "Ravi", "name_original": MALAYALAM_RAVI, "trade": "mason"}
    )

    assert line["worker_name"] == "Ravi"
    assert line["worker_name_original"] == MALAYALAM_RAVI


def test_a_name_left_in_its_own_script_is_still_recorded_as_the_original():
    """The backstop. Every provider is now asked to transliterate, but a model
    that ignores it must not silently drop the native spelling -- preserved,
    the preview shows what was actually said and one plain correction fixes
    the reading rather than the whole report being redone.

    The name is deliberately not guessed at: there is no transliteration
    table here, and a wrong invented name on a wage record is worse than a
    visibly wrong one.
    """
    from canonicalization.builder import _labour_line

    line = _labour_line({"name": MALAYALAM_RAVI, "trade": "mason"})

    assert line["worker_name_original"] == MALAYALAM_RAVI


def test_a_latin_name_gains_no_original_field():
    """A Latin-script report must not sprout a duplicate of every name -- it
    would read as "Ravi (Ravi)" on the preview."""
    from canonicalization.builder import _labour_line

    assert "worker_name_original" not in _labour_line({"name": "Ravi", "trade": "mason"})


@pytest.mark.parametrize("name", ["José", "O'Brien", "Ravi-Kumar", "Mary Anne"])
def test_an_accent_or_punctuation_is_not_mistaken_for_another_script(name):
    """"Any non-Latin character" would flag all of these and bury the real
    cases in noise, so the check is "no Latin letters at all"."""
    from canonicalization.builder import _is_non_latin

    assert _is_non_latin(name) is False


def test_a_headcount_group_never_gains_an_original_name():
    """"12 helpers" names nobody, so there is no spelling to preserve."""
    from canonicalization.builder import _labour_line

    assert "worker_name_original" not in _labour_line({"trade": "helper", "headcount": 12})


def test_matching_behaves_identically_for_text_voice_and_image():
    """Closes the loop on "test every input path".

    Canonicalization already produces identical `lines` for all three (see
    test_labour_lines_are_identical_across_modalities); this runs the
    simplified matcher over each and pins that an exact name+trade match
    connects, and an unknown name does not, whichever way the report arrived.
    Matching sees a list of lines and nothing about how they were captured,
    so there is no fourth code path for Excel to introduce later either.
    """
    from workflows.labour_update.nodes import match_workers

    fields = {
        "workers": [
            {"name": "Ravi Kumar", "trade": "mason"},
            {"name": "Ajmal", "trade": "helper"},
            {"trade": "helper", "headcount": 12},
        ]
    }
    register = [{"worker_id": "w-ravi", "name": "Ravi Kumar", "trade": "mason"}]

    outcomes = []
    for modality in (InputModality.TEXT, InputModality.VOICE, InputModality.IMAGE):
        lines = _event(fields, modality=modality).fields["lines"]
        update = match_workers(
            {
                "workflow_instance_id": "wf",
                "workflow_key": "labour.attendance",
                "correlation_id": "cor",
                "organization_id": "11111111-1111-4111-8111-111111111111",
                "user_id": "22222222-2222-4222-8222-222222222222",
                "project_id": None,
                "site_id": None,
                "collected_fields": {"lines": lines, "worker_candidates": register},
            }
        )
        assert update["awaiting_slot"] is None, f"{modality} asked a question"
        outcomes.append(
            [line.get("worker_id") for line in update["collected_fields"]["lines"]]
        )

    assert outcomes[0] == outcomes[1] == outcomes[2]
    assert outcomes[0] == ["w-ravi", None, None]
