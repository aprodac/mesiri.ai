"""Request 174 (Phase B): the side-by-side of what today's agent did and what v2 proposed.

Pure formatting over the ``agent_v2_shadow`` rows of ``journey_traces`` (written by
``ShadowRunner``); ``scripts/v2_shadow_report.py`` fetches the rows and prints this.
"""

from __future__ import annotations

import json
from typing import Any


def _args(args: dict[str, Any]) -> str:
    keep = {k: v for k, v in args.items() if v not in (None, "", [])}
    return ", ".join(f"{k}={v}" for k, v in keep.items())


def v2_lines(payload: dict[str, Any]) -> list[str]:
    v2 = payload.get("v2") or {}
    if v2.get("error") and not v2.get("calls"):
        return [f"(v2 failed: {v2['error']})"]
    if v2.get("handed_back") is not None:
        return [f"hand back ({v2['handed_back']})"]
    lines = [f"{c['tool']}({_args(c.get('args') or {})})" for c in v2.get("calls") or []]
    if v2.get("unplaced_figures"):
        lines.append("NOT ON CARD: " + ", ".join(v2["unplaced_figures"]))
    return lines or ["(nothing)"]


def classic_lines(payload: dict[str, Any]) -> list[str]:
    old = payload.get("classic") or {}
    lines = [f"{c['tool']}({_args(c.get('args') or {})})" for c in old.get("calls") or []]
    return lines or ["(no tool)"]


def agree(payload: dict[str, Any]) -> bool | None:
    """True when v2 proposed the same material lines (tool family, material, figure); None when
    v2 left the message (a hand-back is neither right nor wrong here: a person reads it)."""
    v2 = payload.get("v2") or {}
    if not v2.get("took_message"):
        return None
    pairs = {
        "draft_receipt": "save_material_receipt",
        "draft_usage": "save_material_usage",
        "draft_stock_count": "adjust_stock",
        "stock_for": "query_materials",
        "ask": "ask_user",
    }
    mine = sorted((pairs.get(c["tool"], c["tool"]), str((c.get("args") or {}).get("material", "")).lower(),
                   str((c.get("args") or {}).get("quantity", (c.get("args") or {}).get("counted", ""))))
                  for c in v2.get("calls") or [])
    old_calls = (payload.get("classic") or {}).get("calls") or []
    theirs = sorted((c["tool"], str((c.get("args") or {}).get("material", "")).lower(),
                     str((c.get("args") or {}).get("quantity", (c.get("args") or {}).get("counted", ""))))
                    for c in old_calls)
    return mine == theirs


def side_by_side(rows: list[dict[str, Any]]) -> str:
    """One block per message, then the totals."""
    out: list[str] = []
    took = agreed = slow = 0
    for row in rows:
        payload = row["stage_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        verdict = agree(payload)
        mark = {True: "SAME", False: "DIFFERENT", None: "v2 left it"}[verdict]
        took += verdict is not None
        agreed += verdict is True
        ms = (payload.get("v2") or {}).get("ms") or 0
        slow += ms > 9000
        out.append(f"[{row.get('created_at', '')}] {payload.get('message')!r}  -> {mark}  (v2 {ms} ms)")
        out.append("  today: " + " | ".join(classic_lines(payload)))
        out.append("  v2   : " + " | ".join(v2_lines(payload)))
        out.append("")
    out.append(f"{len(rows)} messages; v2 took {took}; same as today's on {agreed}; v2 over 9 s: {slow}")
    return "\n".join(out)
