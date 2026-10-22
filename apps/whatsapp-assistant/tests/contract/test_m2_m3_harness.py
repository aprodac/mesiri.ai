"""M2 -> M3 integration harness (contract level).

Drives the understanding pipeline from shared ``NormalizedMessage`` fixtures in
``scenarios/contracts/m2_to_m3/``. M2-produced messages must validate against
the same fixtures with no transformation glue.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage

REPO = pathlib.Path(__file__).resolve().parents[4]
FIXTURES = REPO / "scenarios" / "contracts" / "m2_to_m3"
VALID = sorted((FIXTURES / "valid").glob("*.json"))
INVALID = sorted((FIXTURES / "invalid").glob("*.json"))


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))




@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_fixtures_parse(path: pathlib.Path) -> None:
    msg = NormalizedMessage.model_validate(_load(path))
    assert msg.message_id and msg.correlation_id
    assert isinstance(msg.modality, InputModality)


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_fixtures_are_rejected(path: pathlib.Path) -> None:
    with pytest.raises(ValidationError):
        NormalizedMessage.model_validate(_load(path))


