"""The welcome screen's invite (WEB-34): setup-progress carries Mesiri's own
WhatsApp number when the deployment sets one. The rest of setup-progress runs
against Postgres in tests/integration/test_setup_progress_postgres.py."""

from __future__ import annotations

import pytest

from mesiri.domains.organizations.setup_router import mesiri_whatsapp_number


@pytest.fixture(autouse=True)
def _fresh_settings():
    from mesiri.bootstrap.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_number_is_returned_as_set(monkeypatch) -> None:
    monkeypatch.setenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", " +91 90000 12345 ")
    assert mesiri_whatsapp_number() == "+91 90000 12345"


def test_mesiris_own_number_when_none_is_set(monkeypatch) -> None:
    # SS-20 (16 Nov): the number people message is Mesiri's own unless the deployment sets another; with the country
    # code, so the dashboard's wa.me links work.
    monkeypatch.delenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", raising=False)
    assert mesiri_whatsapp_number() == "+91 89040 34838"


@pytest.mark.parametrize("configured", ["", "   "])
def test_an_empty_setting_hides_the_number(monkeypatch, configured) -> None:
    monkeypatch.setenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", configured)
    assert mesiri_whatsapp_number() is None
