"""The replay numbers as text (request 185)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .checks import CHECKS, SEVERE, Finding


@dataclass(slots=True)
class Scored:
    key: str
    turns: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(f.check in SEVERE for f in self.findings)


def summary(label: str, scored: Iterable[Scored]) -> str:
    scored = list(scored)
    turns = sum(s.turns for s in scored)
    counts = Counter(f.check for s in scored for f in s.findings)
    severe = sum(n for name, n in counts.items() if name in SEVERE)
    clean = sum(1 for s in scored if s.clean)
    lines = [
        f"== {label} ==",
        f"conversations: {len(scored)}   turns: {turns}   clean conversations: {clean}/{len(scored)}",
        f"severe findings: {severe}   ({severe / turns:.1%} of turns)" if turns else "severe findings: 0",
    ]
    for name in CHECKS:
        mark = " *" if name in SEVERE else ""
        lines.append(f"  {name:<18}{counts.get(name, 0):>5}{mark}")
    return "\n".join(lines)


def details(scored: Iterable[Scored], *, limit: int = 200) -> str:
    out = []
    for s in scored:
        for f in s.findings:
            out.append(f"{s.key}  turn {f.turn:>2}  {f.check:<18} {f.detail[:90]}")
            if len(out) >= limit:
                return "\n".join(out)
    return "\n".join(out)
