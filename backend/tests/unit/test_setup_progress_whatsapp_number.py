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


@pytest.mark.parametrize("configured", [None, "", "   "])
def test_no_number_without_one_set(monkeypatch, configured) -> None:
    if configured is None:
        monkeypatch.delenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", raising=False)
    else:
        monkeypatch.setenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", configured)
    assert mesiri_whatsapp_number() is None
