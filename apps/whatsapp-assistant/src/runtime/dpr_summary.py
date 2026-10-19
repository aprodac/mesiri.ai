"""A short AI-written summary of a frozen DPR, made only from confirmed facts (BE-18).

Approved by Alan 19 Oct: English, neutral and factual, 3-5 sentences, no
opinions or advice ("Plastering on the 3rd floor of Tower A was completed;
18 workers on site; sand delivery was 2 hours late.").

When: once per frozen (APPROVED/PUBLISHED) site or project DPR version,
right before its PDF is made -- runtime/project_auto_dpr.py's send step and
runtime/render_pending_dpr_pdfs.py's drain. Stored in
`daily_report_versions.narrative_summary` and never regenerated once set
(a summary someone typed on a revision wins the same way).

Three rules keep it honest:

- **Only the frozen payload goes in**, reduced by ``summary_facts`` to what
  the report itself prints; anything still marked ``review == "draft"`` is
  dropped (a frozen version shouldn't carry any, so this is defensive).
  Money is left out: labour cost is a figure for the owner's eyes, not a
  line in a neutral summary.
- **No invented numbers.** ``numbers_supported`` rejects a summary carrying
  any number -- in digits or in words -- that the facts don't contain.
- **It never holds the DPR up.** Any failure, a slow answer, or a rejected
  summary means no summary: the DPR goes out exactly as before.

Layering: runtime/, because it does I/O (one LLM call), like
runtime/reply_language.py, whose ReplyComposer this follows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from mesiri_ai.ports.generation import JsonGenerationProvider
from trade_label import trade_label

logger = logging.getLogger(__name__)

#: A DPR waits at most this long for its summary; then it goes without one.
_SUMMARY_TIMEOUT_SECONDS = 8.0

#: Five sentences is ~600 characters; much longer means the model ignored
#: the brief.
_MAX_SUMMARY_CHARS = 700
_MAX_SENTENCES = 6

#: Cost purpose in provider_executions (BE-25, docs/backend/usage-costs.md).
USAGE_PURPOSE = "dpr_summary"

_SYSTEM_PROMPT = """You write the summary at the top of a construction Daily Progress Report (DPR).

You are given FACTS: the confirmed facts of one day, as JSON. Write 3 to 5 short sentences in plain English that say what happened that day.

Rules:
1. Use only the FACTS. Do not add anything that is not in them: no causes, no forecasts, no opinions, no advice, no praise or concern.
2. Neutral and factual, like a site diary. Example: "Plastering on the 3rd floor of Tower A was completed. 18 workers were on site. The sand delivery was 2 hours late."
3. Write every number in digits, exactly as it appears in the FACTS. Do not add, total, convert or round numbers.
4. Mention the most important things first: work done, workers on site, issues and delays, materials received or used. For a project report, name any sites listed in not_reported_sites as "not reported".
5. If there is very little, say so plainly in fewer sentences. Never pad.

Output JSON only: {"summary": "<the summary>"}
"""


def _confirmed(items: Any) -> list[dict[str, Any]]:
    return [i for i in items or [] if isinstance(i, dict) and i.get("review") != "draft"]


def _compact(value: Any) -> Any:
    """Drop empty values so the model isn't tempted to write about them."""
    if isinstance(value, dict):
        out = {k: _compact(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [c for c in (_compact(v) for v in value) if c not in (None, "", [], {})]
    return value


def _is_zero(value: Any) -> bool:
    try:
        return float(value or 0) == 0
    except (TypeError, ValueError):
        return False


def _issue_facts(issues: Any, *, with_site: bool) -> list[dict[str, Any]]:
    out = []
    for issue in _confirmed(issues):
        minutes = issue.get("delay_duration_minutes")
        fact = {
            "type": issue.get("issue_type"),
            "severity": issue.get("severity"),
            "description": issue.get("narrative"),
            "status": issue.get("status"),
            "delay_minutes": minutes,
            # Given so "2 hours late" is a fact, not the model's arithmetic.
            "delay_hours": round(int(minutes) / 60, 1) if minutes else None,
        }
        if with_site:
            fact["site"] = issue.get("site_name")
        out.append(fact)
    return out


def _material_facts(materials: Any) -> list[dict[str, Any]]:
    return [
        {
            "material": m.get("material_name"),
            "unit": m.get("unit"),
            "received": None if _is_zero(m.get("received")) else m.get("received"),
            "used": None if _is_zero(m.get("used")) else m.get("used"),
        }
        for m in materials or []
        if isinstance(m, dict) and not (_is_zero(m.get("received")) and _is_zero(m.get("used")))
    ]


def summary_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """The facts a summary may use: the frozen payload's own figures, minus
    drafts, money, late entries for other days and internal flags."""
    labour = payload.get("labour") or {}
    if payload.get("level") == "PROJECT":
        sites = [s for s in payload.get("sites") or [] if isinstance(s, dict)]
        facts: dict[str, Any] = {
            "report": "project",
            "project": payload.get("project_name"),
            "date": payload.get("report_date"),
            "sites_reported": payload.get("reported_site_count"),
            "sites_total": payload.get("total_site_count"),
            "not_reported_sites": [s.get("site_name") for s in sites if not s.get("reported")],
            "sites": [
                {
                    "site": s.get("site_name"),
                    "work_items": s.get("activity_count"),
                    "open_issues": s.get("open_issue_count"),
                    "workers": s.get("headcount"),
                }
                for s in sites
                if s.get("reported")
            ],
            "workers_on_site": labour.get("headcount"),
            "issues": _issue_facts(payload.get("issues"), with_site=True),
            "materials": _material_facts(payload.get("materials")),
        }
    else:
        conditions = payload.get("conditions") or {}
        facts = {
            "report": "site",
            "project": payload.get("project_name"),
            "site": payload.get("site_name"),
            "date": payload.get("report_date"),
            "work": [
                {
                    "work_type": a.get("work_type"),
                    "description": a.get("narrative"),
                    "status": a.get("status"),
                    "contractor": a.get("contractor"),
                    "quantities": [
                        {"quantity": q.get("quantity"), "unit": q.get("unit")}
                        for q in a.get("quantities") or []
                        if isinstance(q, dict)
                    ],
                }
                for a in _confirmed(payload.get("activities"))
            ],
            "workers_on_site": labour.get("headcount"),
            "workers_by_trade": [
                {"trade": trade_label(t.get("trade")) or t.get("trade"), "workers": t.get("headcount")}
                for t in labour.get("trades") or []
                if isinstance(t, dict)
            ],
            "issues": _issue_facts(payload.get("issues"), with_site=False),
            "materials": _material_facts(payload.get("materials")),
            "weather": conditions.get("weather"),
            "site_working": conditions.get("site_working"),
            "hours_lost": conditions.get("hours_lost"),
        }
    # A day with no workers is a fact worth keeping ("no workers on site").
    workers = facts.get("workers_on_site")
    compacted = _compact(facts)
    if workers == 0:
        compacted["workers_on_site"] = 0
    return compacted


# ---------------------------------------------------------------------------
# The invented-number guard
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NUMBER_WORDS = frozenset(
    {
        "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
        "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
        "eighty", "ninety", "hundred", "thousand", "lakh", "lakhs", "crore", "crores",
        "dozen", "dozens", "half", "double", "twice", "thrice",
    }
)
_WORD = re.compile(r"[a-z]+")


def _normalise_number(raw: str) -> str:
    """"1,200" -> "1200", "18.0" -> "18", "2.50" -> "2.5"."""
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value.lstrip("0") or "0"


def _numbers_in(text: str) -> set[str]:
    return {_normalise_number(m.group()) for m in _NUMBER.finditer(text)}


def numbers_supported(summary: str, facts: dict[str, Any]) -> bool:
    """True when every number in ``summary`` appears in ``facts``: digits
    must match a number in the facts, and number words ("two", "dozen") must
    be words the facts themselves use. "one" is allowed -- it is too common
    in plain English ("one of the sites") to police."""
    source = json.dumps(facts, ensure_ascii=False).lower()
    allowed = _numbers_in(source)
    if not _numbers_in(summary) <= allowed:
        return False
    source_words = set(_WORD.findall(source))
    return all(
        word in source_words for word in _WORD.findall(summary.lower()) if word in _NUMBER_WORDS
    )


def _parse(raw: str, facts: dict[str, Any]) -> str | None:
    """The summary, or None when it shouldn't be trusted."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, str):
        return None
    summary = " ".join(summary.split())
    if not summary or len(summary) > _MAX_SUMMARY_CHARS:
        return None
    if len(re.findall(r"[.!?](?:\s|$)", summary)) > _MAX_SENTENCES:
        return None
    if not numbers_supported(summary, facts):
        logger.warning("dpr_summary.rejected_unsupported_number")
        return None
    return summary


class DprSummaryWriter:
    """Writes one DPR's summary (see module docstring). ``write`` never
    raises: None means the DPR goes out without a summary."""

    def __init__(
        self,
        json_generation: JsonGenerationProvider,
        *,
        timeout_seconds: float = _SUMMARY_TIMEOUT_SECONDS,
    ) -> None:
        self._json = json_generation
        self._timeout = timeout_seconds

    async def write(self, payload: dict[str, Any], *, organization_id: Any) -> str | None:
        from mesiri_ai.usage import usage_scope

        try:
            facts = summary_facts(payload)
        except Exception:  # noqa: BLE001 -- an odd payload costs the summary only
            logger.warning("dpr_summary.facts_failed", exc_info=True)
            return None
        try:
            with usage_scope(organization_id=str(organization_id), purpose=USAGE_PURPOSE):
                raw = await asyncio.wait_for(
                    self._json.generate_json(
                        system_prompt=_SYSTEM_PROMPT,
                        user_prompt=json.dumps({"FACTS": facts}, ensure_ascii=False),
                    ),
                    timeout=self._timeout,
                )
        except Exception:  # noqa: BLE001 -- no summary is always a valid answer
            logger.warning("dpr_summary.generate_failed organization_id=%s", organization_id, exc_info=True)
            return None
        return _parse(raw, facts)


async def ensure_summary(
    writer: DprSummaryWriter | None,
    store: Callable[..., Awaitable[str | None]],
    *,
    version_id: Any,
    organization_id: Any,
    payload: dict[str, Any],
    existing: str | None,
) -> str | None:
    """The version's summary: the one it has, else a new one written and
    stored with ``store`` (PostgresDprRepository.set_narrative_summary, or
    a wrapper giving it a connection). Only for frozen versions -- the
    callers check. Never raises."""
    if existing:
        return existing
    if writer is None:
        return None
    summary = await writer.write(payload, organization_id=organization_id)
    if summary is None:
        return None
    try:
        return await store(version_id=version_id, summary=summary)
    except Exception:  # noqa: BLE001
        logger.warning("dpr_summary.store_failed version_id=%s", version_id, exc_info=True)
        return None
