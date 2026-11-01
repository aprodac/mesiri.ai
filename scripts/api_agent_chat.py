#!/usr/bin/env python3
"""WA-119: chat with the API agent pilot from a terminal.

Logs in to a running Mesiri server with a normal dashboard login, then every
line you type goes to the agent (one model + SOP + the API as tools). Lookups
run at once; entries are listed and saved only when you answer ``y``.

    GEMINI_API_KEY=... python scripts/api_agent_chat.py \
        --url http://localhost:8000 --login supervisor@example.com [--model gemini-2.5-pro]

PYTHONPATH must hold backend/src, shared/contracts/src, platform/ai/src and
apps/whatsapp-assistant/src (as for the test suites). Nothing is saved without
your ``y``; the server's own checks decide what your login may do.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys

import httpx


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="Mesiri server, e.g. http://localhost:8000")
    parser.add_argument("--login", required=True, help="dashboard email or username")
    parser.add_argument("--model", default=os.environ.get("MESIRI_API_AGENT_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--tz", default="Asia/Kolkata")
    parser.add_argument("--show-calls", action="store_true", help="print each tool call and result")
    args = parser.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Set GEMINI_API_KEY.", file=sys.stderr)
        return 2

    from pydantic import SecretStr

    from agent_api.agent import ApiAgent, confirm
    from agent_api.client import ApiClient
    from agent_api.tools import build_tools
    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider
    from mesiri_ai.models import ChatMessage

    password = getpass.getpass(f"Password for {args.login}: ")
    async with httpx.AsyncClient(base_url=args.url, timeout=20) as http:
        login = await http.post("/auth/login", json={"email": args.login, "password": password})
        if login.status_code != 200:
            print(f"Login failed: {login.status_code} {login.text}", file=sys.stderr)
            return 1
        token = login.json()["access_token"]
        me = (await http.get("/auth/me", headers={"Authorization": f"Bearer {token}"})).json()
        openapi = (await http.get("/openapi.json")).json()

    provider = GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=args.model))
    agent = ApiAgent(provider, build_tools(openapi))
    client = ApiClient(base_url=args.url, token=token)
    name = me.get("full_name") or me.get("name") or ""
    history: list[ChatMessage] = []
    print(f"Logged in as {name or args.login}. Model {args.model}. Empty line or Ctrl-D quits.\n")
    try:
        while True:
            try:
                text = input("you> ").strip()
            except EOFError:
                break
            if not text:
                break
            turn = await agent.run(client, text, history=history, sender_name=name, timezone=args.tz)
            if args.show_calls:
                for call in turn.calls:
                    print(f"  · {call['tool']}({json.dumps(call['arguments'], ensure_ascii=False)})")
            print(f"mesiri> {turn.reply or '(no words)'}")
            history += [ChatMessage(role="user", text=text), ChatMessage(role="model", text=turn.reply)]
            if turn.pending:
                for i, entry in enumerate(turn.pending, 1):
                    print(f"  [{i}] {entry.summary}   ({entry.tool} {json.dumps(entry.body, ensure_ascii=False)})")
                if input("Save these? [y/N] ").strip().lower() == "y":
                    for result in await confirm(client, turn.pending):
                        mark = "saved" if result.ok else f"REFUSED {result.status}: {result.body}"
                        print(f"  {result.pending.summary}: {mark}")
                    history.append(ChatMessage(role="user", text="(confirmed: saved)"))
                else:
                    print("  Not saved.")
                    history.append(ChatMessage(role="user", text="(not confirmed: nothing saved)"))
            print()
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
