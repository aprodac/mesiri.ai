"""Guided onboarding (15 Nov): every dashboard page shows how it works from WhatsApp, as a chat preview drawn from
``apps/dashboard/src/lib/module-map.ts``. This guards that the preview tells the truth as both sides keep changing:

- every built page says how it works from WhatsApp (``whatsapp: [...]``) or why it doesn't (``whatsappNone``);
- every example names the WhatsApp assistant's tools that do it, and each one is a real tool in ``ALLOWED``, so a
  tool renamed or removed here fails until the page's example is fixed;
- a "save" example uses a tool that writes (it goes on a card), an "answer" example only tools that read.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_api.tools import ALLOWED

MAP = Path(__file__).resolve().parents[4] / "apps/dashboard/src/lib/module-map.ts"
TOOLS = {a.name: a.method for a in ALLOWED}


def _built_pages() -> list[str]:
    return [line for line in MAP.read_text(encoding="utf-8").splitlines() if "status: 'built'" in line]


def _url(line: str) -> str:
    return re.search(r"url: '([^']+)', status: 'built'", line).group(1)  # type: ignore[union-attr]


def _examples(line: str) -> list[tuple[str, list[str]]]:
    return [(kind, re.findall(r"'([a-z_]+)'", tools))
            for kind, tools in re.findall(r"\{ kind: '(save|answer)', say: .*?, tools: \[([^\]]*)\] \}", line)]


def test_the_map_is_found_and_has_pages() -> None:
    assert len(_built_pages()) > 50


@pytest.mark.parametrize("line", _built_pages(), ids=_url)
def test_every_built_page_says_how_it_works_from_whatsapp(line: str) -> None:
    assert ("whatsapp: [" in line) != ("whatsappNone:" in line), "give whatsapp examples or a whatsappNone line"
    if "whatsapp: [" in line:
        assert _examples(line), "whatsapp examples must each name their tools"


@pytest.mark.parametrize("line", [ln for ln in _built_pages() if "whatsapp: [" in ln], ids=_url)
def test_every_example_uses_real_tools_of_the_right_kind(line: str) -> None:
    for kind, tools in _examples(line):
        assert tools, "an example with no tools"
        unknown = [t for t in tools if t not in TOOLS]
        assert not unknown, f"not WhatsApp-assistant tools (agent_api/tools.py ALLOWED): {unknown}"
        writes = [t for t in tools if TOOLS[t] != "GET"]
        if kind == "save":
            assert writes, "a 'save' example must use a tool that writes"
        else:
            assert not writes, f"an 'answer' example must only read, not {writes}"


# Learn Mesiri (SS-42): a walkthrough's WhatsApp practice and its take-back name their tools the same way, so a
# walkthrough never asks someone to send what WhatsApp can't do.
WALKS = MAP.parent / "walkthroughs.ts"


def _walk_tools() -> list[tuple[str, list[str]]]:
    text = WALKS.read_text(encoding="utf-8")
    return [(say, re.findall(r"'([a-z_]+)'", tools))
            for say, tools in re.findall(r"say: '([^']+)', tools: \[([^\]]*)\]", text)]


def test_walkthroughs_have_whatsapp_practice() -> None:
    assert _walk_tools(), "no WhatsApp practice found in walkthroughs.ts: has its format changed?"


@pytest.mark.parametrize(("say", "tools"), _walk_tools(), ids=lambda v: v if isinstance(v, str) else None)
def test_every_walkthrough_practice_uses_real_writing_tools(say: str, tools: list[str]) -> None:
    assert tools, "a practice with no tools"
    unknown = [t for t in tools if t not in TOOLS]
    assert not unknown, f"not WhatsApp-assistant tools (agent_api/tools.py ALLOWED): {unknown}"
    assert any(TOOLS[t] != "GET" for t in tools), "a practice saves something, so it must use a tool that writes"


# Learn Mesiri (D-L3, review 15 Nov): a practice must never leave a real record the person can't take back. Taking back
# a delivery, a use or a move is a stock correction, allowed only to backend ADJUSTMENT_ROLES; every take-back with one
# of those undo tools must name exactly those roles, so the walkthrough turns the practice into card-only for others.
_STOCK_UNDO = {"undo_receipt", "undo_usage", "undo_transfer"}


def test_stock_take_backs_name_the_roles_that_may_correct() -> None:
    from mesiri.domains.materials.validation import ADJUSTMENT_ROLES

    text = WALKS.read_text(encoding="utf-8")
    adjusters = re.search(r"const ADJUSTERS = \[([^\]]*)\]", text)
    assert adjusters, "walkthroughs.ts must define ADJUSTERS (who may take back a stock movement)"
    assert set(re.findall(r"'([A-Z_]+)'", adjusters.group(1))) == set(ADJUSTMENT_ROLES)
    backs = re.findall(r"takeBack: \{([^}]*)\}", text)
    assert backs, "no take-back steps found in walkthroughs.ts: has its format changed?"
    for back in backs:
        if _STOCK_UNDO & set(re.findall(r"'([a-z_]+)'", back)) or "Correct" in back:
            assert "roles: ADJUSTERS" in back, f"a stock take-back must say who may do it: {back}"
