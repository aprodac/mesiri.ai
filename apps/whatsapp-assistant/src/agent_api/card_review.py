"""WA-264: an AI check of a draft card against what the person said (Ilan, 8 Nov: "does the ai actually check and see
what we are telling to save?").

The code already checks every line as it is prepared (numbers they said, real materials and units, believable sizes,
real record ids), but not the MEANING: "6 rods used, one rod is 5 kg" was held as "5 kg Steel used" and every check
passed. This second AI step reads the conversation, the person's message and the card's structured lines (the same
ones the person sees), and says whether each line records what they meant.

Shadow mode first (company setting ``card_review``, default "shadow"): it runs after the reply has gone, adds no time
and changes nothing; its verdict is written to the trace (stage ``card_review``) and its cost is tagged
``card_review``, so how often it is right is measured on real chats before it may change a reply.

The model's answer is checked by the code too: a problem must name a line that is on the card (or 0 for a missing
thing) and quote words the person actually said; anything else is dropped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

PROMPT = (Path(__file__).with_name("CARD_REVIEW.md")).read_text(encoding="utf-8")
USAGE_PURPOSE = "card_review"
#: The turns of the conversation the check reads (the latest ones).
TURNS = 12
#: A check slower than this is dropped (it runs after the reply; this only bounds the background task).
TIMEOUT_S = 20.0
VERDICTS = frozenset({"ok", "wrong", "unsure"})


@dataclass
class CardVerdict:
    verdict: str
    problems: list[dict[str, Any]] = field(default_factory=list)
    question: str = ""
    dropped: int = 0  # problems the code threw out (no such line, or words the person never said)
    ms: int = 0
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "problems": self.problems, "question": self.question,
                "dropped": self.dropped, "ms": self.ms, **({"error": self.error} if self.error else {})}


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").casefold()).split())


def conversation(history: list[Any], limit: int = TURNS) -> list[str]:
    """The latest turns as "Person: ..." / "Mesiri: ...", oldest first (code notes in brackets left out)."""
    out = []
    for m in history[-limit:]:
        text = (getattr(m, "text", "") or "").strip()
        if not text or (text.startswith("(") and text.endswith(")")):
            continue
        out.append(f"{'Person' if getattr(m, 'role', '') == 'user' else 'Mesiri'}: {text[:600]}")
    return out


def checked(raw: str, lines: list[str], person_words: str) -> CardVerdict:
    """The model's JSON as a verdict the code trusts: unknown verdicts are "unsure"; a problem must point at a line
    on the card (0 = something missing) and quote the person's own words."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return CardVerdict("unsure", error="not JSON")
    if not isinstance(data, dict):
        return CardVerdict("unsure", error="not an object")
    verdict = str(data.get("verdict") or "").strip().lower()
    verdict = verdict if verdict in VERDICTS else "unsure"
    said = _plain(person_words)
    kept, dropped = [], 0
    for p in data.get("problems") or []:
        if not isinstance(p, dict):
            dropped += 1
            continue
        try:
            line = int(p.get("line") or 0)
        except (TypeError, ValueError):
            line = -1
        quote = _plain(str(p.get("said") or ""))
        if not 0 <= line <= len(lines) or not quote or quote not in said:
            dropped += 1
            continue
        kept.append({"line": line, "problem": str(p.get("problem") or "")[:300], "said": str(p.get("said"))[:200],
                     "should_be": str(p.get("should_be") or "")[:200]})
    if verdict == "wrong" and not kept:
        verdict = "unsure"  # a "wrong" with nothing that holds up is not a finding
    if verdict == "ok":
        kept = []
    return CardVerdict(verdict, kept, str(data.get("question") or "")[:300] if verdict == "wrong" else "", dropped)


async def review_card(provider: Any, *, said: str, lines: list[str], history: list[Any], organization_id: str,
                      correlation_id: str | None = None) -> CardVerdict | None:
    """The check of one card. None when the provider cannot do it (no JSON call) or there is no card."""
    generate = getattr(provider, "generate_json", None)
    if generate is None or not lines or not said.strip():
        return None
    convo = conversation(history)
    person_words = " ".join([said, *(c.removeprefix("Person: ") for c in convo if c.startswith("Person: "))])
    prompt = json.dumps({"CONVERSATION": convo, "THIS_MESSAGE": said, "CARD": lines}, ensure_ascii=False)
    started = time.monotonic()
    try:
        from mesiri_ai.usage import usage_scope

        with usage_scope(organization_id=organization_id, purpose=USAGE_PURPOSE):
            raw = await asyncio.wait_for(generate(system_prompt=PROMPT, user_prompt=prompt,
                                                  correlation_id=correlation_id), timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 -- a check that fails is logged, never felt
        return CardVerdict("unsure", error=type(exc).__name__, ms=int((time.monotonic() - started) * 1000))
    verdict = checked(raw, lines, person_words)
    verdict.ms = int((time.monotonic() - started) * 1000)
    return verdict
