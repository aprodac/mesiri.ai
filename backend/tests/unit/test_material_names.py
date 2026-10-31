"""Request 165: a material's catalogue name is English, in Latin letters."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from mesiri.domains.materials.names import (
    MaterialNameError,
    alias_key,
    is_latin_name,
    require_latin_name,
)
from mesiri.domains.materials.router import MaterialCatalogCreate, create_material


@pytest.mark.parametrize("name", ["Laterite stone", "M sand", "TMT steel bars 12mm", "Wire-cut bricks", "20 mm metal", "Cement (OPC 53)"])
def test_english_names_pass_unchanged(name):
    assert require_latin_name(f"  {name} ") == name


@pytest.mark.parametrize("name", ["ചെങ്കല്ല്", "Laterite ചെങ്കല്ല്", "सीमेंट", "செங்கல்"])
def test_non_latin_letters_are_refused(name):
    assert not is_latin_name(name)
    with pytest.raises(MaterialNameError):
        require_latin_name(name)


def test_alias_key_makes_malayalam_spelling_variants_equal():
    assert alias_key("സിമൻറ്") == alias_key("  സിമന്റ്  ")
    assert alias_key("Chenkallu ") == "chenkallu"


async def test_api_refuses_a_malayalam_name_with_422():
    body = MaterialCatalogCreate(name="ചെങ്കല്ല്", default_unit_id=uuid.uuid4())
    with pytest.raises(HTTPException) as err:
        await create_material(body, auth_context=object(), conn=object())  # type: ignore[arg-type]
    assert err.value.status_code == 422
    assert "English" in err.value.detail
