"""Fetch the anonymised assistant review export (WA-14) to a local JSON file.

Run by the scheduled Claude Code reviewer (docs/ops/assistant-review.md), or by
hand. Logs in as a platform admin and calls GET /admin/review/export.

Environment:
  MESIRI_REVIEW_API       base URL (default https://api.whatsapp.mesiri.ai)
  MESIRI_REVIEW_TOKEN     a platform-admin JWT, or instead:
  MESIRI_REVIEW_EMAIL     platform-admin login
  MESIRI_REVIEW_PASSWORD

Usage:
  python apps/whatsapp-assistant/scripts/fetch_review_export.py OUT.json [--hours 24]

Prints a one-line summary. Exits non-zero on any failure, so a scheduled run
reports it instead of reviewing an empty file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def _token(client: httpx.Client) -> str:
    token = os.environ.get("MESIRI_REVIEW_TOKEN")
    if token:
        return token
    email = os.environ.get("MESIRI_REVIEW_EMAIL")
    password = os.environ.get("MESIRI_REVIEW_PASSWORD")
    if not email or not password:
        sys.exit("Set MESIRI_REVIEW_TOKEN, or MESIRI_REVIEW_EMAIL and MESIRI_REVIEW_PASSWORD.")
    resp = client.post("/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    base = os.environ.get("MESIRI_REVIEW_API", "https://api.whatsapp.mesiri.ai")
    with httpx.Client(base_url=base, timeout=120) as client:
        token = _token(client)
        resp = client.get(
            "/admin/review/export",
            params={"hours": args.hours, "limit": args.limit},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        export = resp.json()

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(export, fh, ensure_ascii=False, indent=1)

    s = export["summary"]
    print(
        f"{s['messages']} messages, {s['conversations']} conversations, "
        f"{s['users']} users, {s['companies']} companies, status {s['by_status']}"
        + (" -- TRUNCATED, raise --limit" if export.get("truncated") else "")
    )


if __name__ == "__main__":
    main()
