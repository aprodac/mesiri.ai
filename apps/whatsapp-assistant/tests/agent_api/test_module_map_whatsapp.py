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


# Learn Mesiri (D-L3, reviews 15 and 16 Nov): a practice must never leave a real record the person can't take back.
# Some undos are limited by role in the backend; a take-back with one of these tools must name, as `roles:`, the list in
# walkthroughs.ts that equals the backend's, so the walkthrough turns the practice into card-only for everyone else.
# Found twice: a site engineer's practice delivery (stock correction) and a project manager's practice expense.
def _role_limited_undos() -> dict[str, tuple[str, frozenset[str]]]:
    from mesiri.authorization.roles import MONEY_MANAGE_ROLES
    from mesiri.domains.materials.validation import ADJUSTMENT_ROLES

    stock = ("ADJUSTERS", frozenset(ADJUSTMENT_ROLES))
    return {"undo_receipt": stock, "undo_usage": stock, "undo_transfer": stock,
            "undo_expense": ("MONEY_MANAGERS", frozenset(MONEY_MANAGE_ROLES))}


def test_role_limited_take_backs_name_the_backends_roles() -> None:
    text = WALKS.read_text(encoding="utf-8")
    undos = _role_limited_undos()
    for const, roles in set(undos.values()):
        found = re.search(rf"const {const} = \[([^\]]*)\]", text)
        assert found, f"walkthroughs.ts must define {const}"
        assert set(re.findall(r"'([A-Z_]+)'", found.group(1))) == set(roles), f"{const} differs from the backend"
    backs = re.findall(r"takeBack: \{([^}]*)\}", text)
    assert backs, "no take-back steps found in walkthroughs.ts: has its format changed?"
    for back in backs:
        tools = set(re.findall(r"'([a-z_]+)'", back))
        wanted = {undos[t][0] for t in tools if t in undos} | ({"ADJUSTERS"} if "Correct" in back else set())
        for const in wanted:
            assert f"roles: {const}" in back, f"this take-back must say who may do it (roles: {const}): {back}"
