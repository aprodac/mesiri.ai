"""[224] (3 Nov 23:54, Ilan, Paraclette, cor ...1e89f4): English all evening, a Confirm ✅ tap on a preview was thanked in
Manglish. Root cause: two records of a person's language; a tap has no words, and the code-worded tap replies read
the classic profile (Manglish, from older messages) instead of the language v3 keeps from their latest words.
Fix: one ``_tap_language`` in the journey; a company on v3 asks ``ApiWhatsApp.reply_language`` (the language they
chose, WA-169, else their latest words'), the profile only when v3 knows nothing.
Siblings: Change it, the release note's Works ✅ / Still wrong ❌. Guards: a Manglish writer still gets Manglish; a
classic company still uses the profile; no v3 state = the profile as before.
"""

from __future__ import annotations

import functools

import pytest
from tests.agent_api.test_api_whatsapp_119 import FakeRedis, Harness, _message, _stand_in_tools  # noqa: F401 (autouse)
from tests.unit.test_agent_routing import ASK

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider

CID = "cor_0123456789abcdef0123456789abcdef"
EN = "Thanks 👍 We'll finish it like that"
MANGLISH = "Thanks 👍 Ingane thanne theerkkaam"


class StateRedis(FakeRedis):
    """v3's state for whoever the test sender is (their user id is made by the journey builder)."""

    def __init__(self, state: dict | None) -> None:
        super().__init__()
        self.v3_state = state

    async def get_json(self, key: str):  # noqa: ANN201
        if key.startswith("agent_api:") and key.count(":") == 2 and self.v3_state is not None:
            return dict(self.v3_state)
        return await super().get_json(key)


class Profile:
    """The classic profile: Manglish, from older messages."""

    async def get_profile(self, *, user_id: str):  # noqa: ANN201
        return "Malayalam", "latin"


def _journey(monkeypatch, mode: str, state: dict | None):  # noqa: ANN202
    from tests.unit.test_agent_routing import _build

    model = FakeToolCallingProvider(list(ASK._script))
    harness = Harness(model)
    real_init = wa.ApiWhatsApp.__init__

    def init(self, **kwargs):  # noqa: ANN001, ANN003
        kwargs["app"] = harness.app
        real_init(self, **kwargs)

    monkeypatch.setattr(wa.ApiWhatsApp, "__init__", init)
    import runtime.message_journey as mj

    real_build = mj.build_message_handlers

    @functools.wraps(real_build)
    def build(**deps):  # noqa: ANN003
        return real_build(**deps, material_db=object(), redis_client=StateRedis(state), user_language_store=Profile())

    monkeypatch.setattr(mj, "build_message_handlers", build)
    on_normalized, deps, _ = _build(monkeypatch, mode=mode, provider=model)
    return on_normalized, deps


def _texts(deps) -> list[str]:  # noqa: ANN001
    return [c.args[1] for c in deps["sender"].send_text.await_args_list]


async def test_the_reported_confirm_tap_is_thanked_in_english(monkeypatch) -> None:
    on_normalized, deps = _journey(monkeypatch, "api", {"language": "english"})
    await on_normalized(_message("Confirm ✅", tap=f"preview_ok:{CID}"), {})
    assert any(EN in t for t in _texts(deps)), _texts(deps)


@pytest.mark.parametrize(("tap", "english"), [
    (f"preview_change:{CID}", "What should be different?"),
    ("release_ok:lookup-as-image", "Glad it works"),
    ("release_bad:lookup-as-image", "looking at what went wrong"),
])
async def test_siblings_every_tap_reply_follows_their_latest_words(monkeypatch, tap, english) -> None:
    on_normalized, deps = _journey(monkeypatch, "api", {"language": "english"})
    await on_normalized(_message("tap", tap=tap), {})
    assert any(english in t for t in _texts(deps)), _texts(deps)


async def test_a_chosen_language_wins_for_a_tap_too(monkeypatch) -> None:
    on_normalized, deps = _journey(monkeypatch, "api", {"language": "english", "chosen_language": "malayalam"})
    await on_normalized(_message("Confirm ✅", tap=f"preview_ok:{CID}"), {})
    assert any("നന്ദി" in t for t in _texts(deps)), _texts(deps)


async def test_guard_a_manglish_writer_still_gets_manglish(monkeypatch) -> None:
    on_normalized, deps = _journey(monkeypatch, "api", {"language": "manglish"})
    await on_normalized(_message("Confirm ✅", tap=f"preview_ok:{CID}"), {})
    assert any(MANGLISH in t for t in _texts(deps)), _texts(deps)


@pytest.mark.parametrize(("mode", "state"), [("api", None), ("classic", {"language": "english"})])
async def test_guard_no_v3_language_or_classic_uses_the_profile_as_before(monkeypatch, mode, state) -> None:
    on_normalized, deps = _journey(monkeypatch, mode, state)
    await on_normalized(_message("Confirm ✅", tap=f"preview_ok:{CID}"), {})
    assert any(MANGLISH in t for t in _texts(deps)), _texts(deps)
