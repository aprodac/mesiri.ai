"""v2's skills (request 174, every module request 185).

A skill is a folder: ``SKILL.md`` (the rules, plain English), ``tools.py`` (what the agent may
call) and ``evals.yaml`` (what a good run does). ``general`` is read first, the module skills
next, ``materials`` (its own v2 tool names) last.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

DIR = Path(__file__).resolve().parent
#: The module skills whose tools are today's tools under their own names.
MODULES = ("labour", "work", "issues", "expenses", "site", "reports")
#: Rule files in the order the model reads them.
ORDER = ("general", *MODULES, "materials")


def rule_files() -> tuple[Path, ...]:
    return tuple(DIR / name / "SKILL.md" for name in ORDER)


def module_tools() -> tuple[frozenset[str], frozenset[str]]:
    """``(write tools, read tools)`` of every module skill."""
    write: set[str] = set()
    read: set[str] = set()
    # Request 194: ``general`` has tools too (undo / change of a saved entry, any module).
    for name in ("general", *MODULES):
        tools = import_module(f"{__name__}.{name}.tools")
        write |= tools.WRITE_TOOLS
        read |= tools.READ_TOOLS
    return frozenset(write), frozenset(read)
