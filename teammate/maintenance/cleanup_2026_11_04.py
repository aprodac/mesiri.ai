"""TM-76: the one-time request-log cleanup approved on 4 Nov 2026 (135 open/in-progress -> about 35).

Prints what it would change; nothing is written without --apply:

    python3 teammate/maintenance/cleanup_2026_11_04.py            # dry run
    python3 teammate/maintenance/cleanup_2026_11_04.py --apply    # writes to the bot's request log

Needs TEAMMATE_TOKEN (and TEAMMATE_PROJECT=mesiri, set in .claude/settings.json). A request that has
moved since 4 Nov (no longer open / in progress, or changed after 4 Nov 12:00 UTC) is skipped, so
running it late never undoes newer work. Safe to run twice.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inbox  # noqa: E402

TAG = "cleanup 4 Nov"
CUTOFF = "2026-11-04T12:00:00"

#: A: replaced by a later request.
REPLACED = {
    57: [19, 20, 44, 55, 56], 37: [34], 49: [48], 51: [50], 61: [60], 66: [64], 68: [65], 84: [83],
    123: [97, 122], 116: [112], 158: [152, 153, 154, 155, 156], 186: [185], 188: [187], 193: [189],
}
#: B: built for the old assistant (classic, the ADR agent, draft_v2, v2), which v3 replaced on 2 Nov.
OLD_ASSISTANT = [
    40, 172, 173, 175, 177, 179, 193, 84, 85, 88, 89, 90, 99, 43, 45, 46, 47, 53, 58, 59, 63, 68, 75, 76,
    114, 115, 133, 116, 123, 124, 125, 126, 127,
]
#: C: one-off tasks that are clearly finished, with the evidence.
DONE = {
    41: "deploys run from aprodac/mesiri.ai (INF-03)", 42: "CI green since", 113: "CI green since",
    52: "production redeployed since", 61: "@bot auto on exists (teammate/README)",
    66: "docs/qa/CONVERSATION_SCORECARD.md exists", 78: "120/h guard in teammate/listener/src/api.js",
    79: "docs/qa/runs/2026-10-21-WA-35-36", 80: "docs/qa/runs/2026-10-21-WA-35-36",
    81: "docs/qa/runs/2026-10-21-round-3", 134: "docs/qa/runs/2026-10-27-whatsapp-live-tests",
    86: "one-off test", 15: "bot DMs + test chat exist", 16: "bot answers voice replies",
    32: "test_assistant taps menu options", 117: "test_assistant reports reply times and sends voice",
    30: "SS-16, 28e9d36",
}
#: D: ideas, kept as Later rows in docs/plans/V1_TRACKER.md.
IDEAS = {
    17: "WA-176", 18: "WA-177", 21: "WA-178", 23: "WA-179", 26: "WA-180", 27: "WA-181", 28: "WA-182",
    105: "WA-183", 22: "TM-81", 31: "TM-82", 138: "TM-77 / TM-80", 87: "docs/plans/ux-cards-plan.md",
    91: "docs/plans/ux-cards-plan.md",
}
#: E: no activity for over a week; an owner says done, keep or drop (shown as "needs a decision").
DECIDE = [24, 37, 38, 49, 51, 67, 92, 93, 94, 96, 103, 108, 110, 111]


def plan() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for new, olds in REPLACED.items():
        for n in olds:
            out[n] = {"status": "wont_do", "note": f"{TAG}: replaced by [{new}]"}
    for n in OLD_ASSISTANT:
        out.setdefault(n, {"status": "wont_do", "note": f"{TAG}: built for the old assistant, replaced by v3 (2 Nov); log a new request if it still happens on v3"})
    for n, why in DONE.items():
        out[n] = {"status": "done", "note": f"{TAG}: already shipped ({why})", **({"ref": "28e9d36"} if n == 30 else {})}
    for n, where in IDEAS.items():
        out[n] = {"status": "wont_do", "note": f"{TAG}: idea kept as a Later item ({where}); the log holds only work in progress"}
    for n in DECIDE:
        out[n] = {"status": "open", "held": f"{TAG}: no activity for over a week. Done, still a problem on v3, or drop?"}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the changes (default: print only)")
    a = ap.parse_args()
    live = {}
    for status in ("open", "in_progress"):
        for i in inbox._request("GET", "/items", params={"status": status, "project": inbox.PROJECT})["items"]:
            live[i["id"]] = i
    changed = skipped = 0
    for n, change in sorted(plan().items()):
        item = live.get(n)
        if not item or item["updated_at"] > CUTOFF:
            print(f"[{n:>3}] skip: {'not open any more' if not item else 'changed after 4 Nov'}")
            skipped += 1
            continue
        print(f"[{n:>3}] {item['status']} -> {change['status']}: {change.get('note') or change.get('held')}")
        if a.apply:
            inbox._request("POST", f"/items/{n}", body={**change, "project": inbox.PROJECT})
        changed += 1
    print(f"\n{'changed' if a.apply else 'would change'} {changed}, skipped {skipped}. Left open: {len(live) - changed}.")


if __name__ == "__main__":
    main()
