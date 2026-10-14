"""Read and record the nightly reviewer's findings (WA-15) through the admin API.

Same login as fetch_review_export.py (MESIRI_REVIEW_TOKEN, or
MESIRI_REVIEW_EMAIL + MESIRI_REVIEW_PASSWORD; MESIRI_REVIEW_API for the base URL).

  python apps/whatsapp-assistant/scripts/review_findings.py list [--status open]
  python apps/whatsapp-assistant/scripts/review_findings.py record FINDINGS.json
  python apps/whatsapp-assistant/scripts/review_findings.py update FINGERPRINT --status fixed --commit abc1234
  python apps/whatsapp-assistant/scripts/review_findings.py friction [--days 14]

FINDINGS.json: {"seen_on": "YYYY-MM-DD", "findings": [{"fingerprint", "category", "title",
"detail", "suspected_location", "workflow_key", "severity" 1-3, "occurrences",
"examples": ["u_xxxx @ HH:MM"], "replay_cases": ["case-id"]}]}. See docs/ops/assistant-review.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from fetch_review_export import _token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=["open", "fixing", "fixed", "wont_fix"])
    rec = sub.add_parser("record")
    rec.add_argument("file")
    upd = sub.add_parser("update")
    upd.add_argument("fingerprint")
    upd.add_argument("--status", choices=["open", "fixing", "fixed", "wont_fix"])
    upd.add_argument("--commit")
    upd.add_argument("--note")
    upd.add_argument("--replay-case", action="append", dest="replay_cases")
    fr = sub.add_parser("friction")
    fr.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    base = os.environ.get("MESIRI_REVIEW_API", "https://api.whatsapp.mesiri.ai")
    with httpx.Client(base_url=base, timeout=120) as client:
        headers = {"Authorization": f"Bearer {_token(client)}"}
        if args.cmd == "list":
            resp = client.get(
                "/admin/review/findings",
                params={"status": args.status} if args.status else {},
                headers=headers,
            )
        elif args.cmd == "record":
            body = json.loads(Path(args.file).read_text(encoding="utf-8"))
            resp = client.post("/admin/review/findings", json=body, headers=headers)
        elif args.cmd == "update":
            patch = {
                "status": args.status,
                "fix_commit": args.commit,
                "note": args.note,
                "replay_cases": args.replay_cases,
            }
            resp = client.patch(
                f"/admin/review/findings/{args.fingerprint}",
                json={k: v for k, v in patch.items() if v is not None},
                headers=headers,
            )
        else:
            resp = client.get("/admin/review/friction", params={"days": args.days}, headers=headers)
        if resp.status_code >= 400:
            sys.exit(f"HTTP {resp.status_code}: {resp.text}")
        print(json.dumps(resp.json(), indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
