"""SS-02: the WhatsApp gates use the shared company-lifecycle rule.

A trial company must be let in until its trial ends, and shut out after,
without any job flipping its status. Both the live identity gate and the
projection into the assistant's context copy must ask
lifecycle.is_operational instead of comparing status to "active" by hand,
or a trial company would be told it is suspended on its first message.
"""

from __future__ import annotations

from pathlib import Path

_APP_SRC = Path(__file__).resolve().parents[2] / "src"


def _source(*parts: str) -> str:
    return _APP_SRC.joinpath(*parts).read_text(encoding="utf-8")


def test_live_identity_gate_uses_lifecycle_rule():
    src = _source("backend", "postgres", "actor.py")
    assert "o.trial_ends_at AS org_trial_ends_at" in src
    assert "org_active=is_operational(" in src
    assert "_ORG_ACTIVE_STATUS" not in src


def test_context_projection_uses_lifecycle_rule():
    src = _source("context", "identity_projection.py")
    assert "SELECT id, name, status, trial_ends_at FROM organizations WHERE id = :id" in src
    assert 'is_active = is_operational(row["status"], row.get("trial_ends_at")' in src
