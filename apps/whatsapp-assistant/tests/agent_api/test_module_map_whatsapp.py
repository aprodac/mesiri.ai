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
