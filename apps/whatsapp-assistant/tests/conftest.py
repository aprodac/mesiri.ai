"""Shared test fixtures for WhatsApp ingress."""

from __future__ import annotations

import hashlib
import hmac
import importlib.machinery
import importlib.util
import json
import os
import sys
import sysconfig
from typing import Any

_stdlib_dir = sysconfig.get_path("stdlib")
_platform_py = os.path.join(_stdlib_dir, "platform.py")
if os.path.isfile(_platform_py):
    _loader = importlib.machinery.SourceFileLoader("_stdlib_platform", _platform_py)
    _spec = importlib.util.spec_from_loader("_stdlib_platform", _loader)
    _mod = importlib.util.module_from_spec(_spec)
    _loader.exec_module(_mod)
    sys.modules["platform"] = _mod

import pytest
from httpx import ASGITransport, AsyncClient

from runtime.dependencies import Settings
from runtime.lifecycle import create_app

# TM-20: a CI run with live tests names a file here; scripts/report_ci_gemini_usage.py reports it afterwards.
_USAGE_LOG = os.environ.get("MESIRI_USAGE_LOG")


def _log_usage(report: Any) -> None:
    with open(_USAGE_LOG, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "provider": report.provider,
                    "model": report.model,
                    "input_tokens": report.input_tokens,
                    "cached_input_tokens": report.cached_input_tokens,
                    "audio_input_tokens": report.audio_input_tokens,
                    "output_tokens": report.output_tokens,
                }
            )
            + "\n"
        )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item: pytest.Item) -> None:
    # Before each test body, not once: a fixture that starts the app installs its own sink.
    if _USAGE_LOG:
        from mesiri_ai import usage

        usage.set_usage_sink(_log_usage)


@pytest.fixture
def settings() -> Settings:
    """Return test settings for WhatsApp ingress."""
    return Settings(
        verify_token="test-verify-token",
        app_secret="test-app-secret",
        access_token="test-access-token",
        api_version="v21.0",
    )


@pytest.fixture
def app(settings: Settings):
    """Return a configured FastAPI application."""
    return create_app(settings=settings)


@pytest.fixture
async def client(app):
    """Return an async HTTP client bound to the FastAPI application."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client


def sign_payload(payload: dict[str, Any], app_secret: str) -> tuple[str, bytes]:
    """Generate a Meta-compatible webhook signature header and canonical body."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}", body
