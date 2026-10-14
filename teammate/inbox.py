#!/usr/bin/env python3
"""inbox -- read what was said in the team's and customers' WhatsApp groups.

The command Claude Code sessions (and people) use to reach the teammate
listener's inbox API. Standard library only, so it runs anywhere.

Environment:
  TEAMMATE_TOKEN   the listener's API token (required)
  TEAMMATE_API     default https://api.whatsapp.mesiri.ai/teammate
  TEAMMATE_TZ      timezone for printed times, default Asia/Kolkata
  TEAMMATE_PROJECT this repo's project, e.g. mesiri or mercon (set in the repo's
                   .claude/settings.json). Every command then sees and posts to
                   that project's groups only; unset, everything is visible.

Commands:
  status                              is the listener linked and receiving?
  chats                               every group/chat with its label and counts
  label <chat> team|customer|ignore [--project P]
                                      label a chat (name substring or jid); the project
                                      defaults to TEAMMATE_PROJECT
  recent [--chat X] [--role R] [--hours 24] [--limit 100]
  search <words...> [--chat X] [--role R] [--days 60] [--limit 50]
  show <n> [--around 10]              one message with the conversation around it
  media <n> <out-file>                download a photo / voice note / document
  pair <phone-with-country-code>      link the spare number (prints a code to type on the phone)
  post [text] [--text-file F] [--image FILE[::caption] ...] [--chat X]
                                      post into the TEAM group (customer groups are refused)

Messages are numbered (#1432). Refer to them by number when asking for a fix.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc  # noqa: UP017 -- datetime.UTC needs Python 3.11; this runs on 3.9+
API = os.environ.get("TEAMMATE_API", "https://api.whatsapp.mesiri.ai/teammate").rstrip("/")
PROJECT = os.environ.get("TEAMMATE_PROJECT") or None
_TZ_NAME = os.environ.get("TEAMMATE_TZ", "Asia/Kolkata")
try:
    TZ = ZoneInfo(_TZ_NAME)
except ZoneInfoNotFoundError:
    # Windows Python ships without time zone data (pip install tzdata adds it).
    TZ = timezone(timedelta(hours=5, minutes=30)) if _TZ_NAME == "Asia/Kolkata" else UTC


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    raw: bool = False,
):
    token = os.environ.get("TEAMMATE_TOKEN")
    if not token and path != "/health":
        sys.exit("TEAMMATE_TOKEN is not set (add it to this environment's secrets).")
    query = (
        "?"
        + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
        if params
        else ""
    )
    req = urllib.request.Request(
        API + path + query,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if token
        else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        sys.exit(f"{method} {path} -> HTTP {err.code}: {detail}")
    except urllib.error.URLError as err:
        sys.exit(f"cannot reach {API}: {err.reason}")
    return data if raw else json.loads(data)


def _when(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ).strftime("%d %b %H:%M")


def _who(m: dict) -> str:
    if m.get("from_me"):
        return "(linked number)"
    name = m.get("sender_name") or "?"
    pn = (m.get("sender_pn") or m.get("sender_jid") or "").split("@")[0]
    return f"{name} (…{pn[-4:]})" if pn.isdigit() else name


def _line(m: dict, *, with_chat: bool = True) -> str:
    chat = f"[{m.get('chat_name') or m['chat_jid']} · {m.get('chat_role')}] " if with_chat else ""
    kind = "" if m["kind"] == "text" else f"<{m['kind']}{' ✓file' if m.get('has_media') else ''}> "
    text = (m.get("text") or "").replace("\n", " ⏎ ")
    quoted = f'  ↩ "{(m["quoted_text"] or "")[:80]}"' if m.get("quoted_text") else ""
    return f"#{m['n']:<6} {_when(m['at'])}  {chat}{_who(m)}: {kind}{text}{quoted}"


def _print_messages(messages: list[dict], *, oldest_first: bool = True) -> None:
    if not messages:
        print("(no messages)")
        return
    for m in reversed(messages) if oldest_first else messages:
        print(_line(m))


def _since(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat().replace("+00:00", "Z")


def _resolve_chat(name_or_jid: str) -> str:
    if "@" in name_or_jid:
        return name_or_jid
    chats = _request("GET", "/chats", params={"project": PROJECT})["chats"]
    hits = [c for c in chats if name_or_jid.lower() in (c.get("name") or "").lower()]
    if len(hits) != 1:
        names = ", ".join(c.get("name") or c["jid"] for c in hits) or "none"
        sys.exit(
            f"'{name_or_jid}' matches {len(hits)} chats ({names}); be more specific or use the jid"
        )
    return hits[0]["jid"]


def _team_chat(explicit: str | None) -> str:
    if explicit:
        return explicit
    chats = _request("GET", "/chats", params={"project": PROJECT})["chats"]
    teams = [
        c for c in chats if c["role"] == "team" and (not PROJECT or c.get("project") == PROJECT)
    ]
    if len(teams) != 1:
        names = ", ".join(c.get("name") or c["jid"] for c in teams) or "none"
        sys.exit(f"{len(teams)} chats are labelled team ({names}); pass --chat")
    return teams[0]["jid"]


def _post(a: argparse.Namespace) -> None:
    text = a.text
    if a.text_file:
        with open(a.text_file, encoding="utf-8") as fh:
            text = fh.read().strip()
    if not text and not a.image:
        sys.exit("nothing to post: give text, --text-file or --image")
    chat = _team_chat(a.chat)
    if text:
        r = _request("POST", "/send", body={"chat": chat, "project": PROJECT, "text": text})
        print(f"posted text to {r['chat']}")
    for spec in a.image:
        path, _, caption = spec.partition("::")
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode()
        r = _request(
            "POST",
            "/send",
            body={
                "chat": chat,
                "project": PROJECT,
                "image_base64": data,
                "caption": caption or None,
            },
        )
        print(f"posted {path} to {r['chat']}")


def main() -> None:
    # Windows consoles default to a legacy code page that can't print · … ⏎.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        prog="inbox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("chats")
    lab = sub.add_parser("label")
    lab.add_argument("chat")
    lab.add_argument("role", choices=["team", "customer", "ignore", "unlabelled"])
    lab.add_argument("--project", default=PROJECT, help="default: TEAMMATE_PROJECT")
    rec = sub.add_parser("recent")
    rec.add_argument("--chat")
    rec.add_argument("--role", choices=["team", "customer", "unlabelled"])
    rec.add_argument("--hours", type=float, default=24)
    rec.add_argument("--limit", type=int, default=100)
    sea = sub.add_parser("search")
    sea.add_argument("words", nargs="+")
    sea.add_argument("--chat")
    sea.add_argument("--role", choices=["team", "customer", "unlabelled"])
    sea.add_argument("--days", type=float, default=60)
    sea.add_argument("--limit", type=int, default=50)
    sho = sub.add_parser("show")
    sho.add_argument("n", type=int)
    sho.add_argument("--around", type=int, default=10)
    med = sub.add_parser("media")
    med.add_argument("n", type=int)
    med.add_argument("out")
    pai = sub.add_parser("pair")
    pai.add_argument("phone")
    pos = sub.add_parser("post")
    pos.add_argument("text", nargs="?")
    pos.add_argument("--text-file", help="read the message from a file (for longer updates)")
    pos.add_argument(
        "--image", action="append", default=[], help="FILE or FILE::caption; repeat for several"
    )
    pos.add_argument("--chat", help="team chat name or jid; default: the only chat labelled team")
    a = p.parse_args()

    if a.cmd == "status":
        h = _request("GET", "/health")
        wa, ib = h["whatsapp"], h["inbox"]
        print(
            f"WhatsApp: {wa['state']}"
            + (f" as …{wa['linked_as'][-4:]}" if wa.get("linked_as") else "")
        )
        print(
            f"Inbox: {ib['messages']} messages in {ib['chats']} chats; last message {_when(ib.get('last_message_at'))}"
        )
    elif a.cmd == "chats":
        for c in _request("GET", "/chats", params={"project": PROJECT})["chats"]:
            kind = "group" if c["is_group"] else "direct"
            print(
                f"{c['role']:<10} {c.get('project') or '-':<10} {c['messages']:>6} msgs  last {_when(c.get('last_message_at')):<13} {kind:<6} {c.get('name') or '?'}  ({c['jid']})"
            )
    elif a.cmd == "label":
        jid = _resolve_chat(a.chat)
        body = {"jid": jid, "role": a.role}
        if a.project:
            body["project"] = a.project
        _request("POST", "/chats/role", body=body)
        print(f"{jid} labelled {a.role}" + (f", project {a.project}" if a.project else ""))
    elif a.cmd == "recent":
        params = {
            "chat": a.chat,
            "role": a.role,
            "project": PROJECT,
            "since": _since(hours=a.hours),
            "limit": a.limit,
        }
        _print_messages(_request("GET", "/messages", params=params)["messages"])
    elif a.cmd == "search":
        params = {
            "q": " ".join(a.words),
            "chat": a.chat,
            "role": a.role,
            "project": PROJECT,
            "since": _since(days=a.days),
            "limit": a.limit,
        }
        _print_messages(_request("GET", "/messages", params=params)["messages"])
    elif a.cmd == "show":
        ctx = _request("GET", f"/messages/{a.n}", params={"around": a.around, "project": PROJECT})
        m = ctx["message"]
        print(f"{m.get('chat_name') or m['chat_jid']} ({m.get('chat_role')})\n")
        for t in ctx["thread"]:
            mark = ">>" if t["n"] == m["n"] else "  "
            print(mark, _line(t, with_chat=False))
    elif a.cmd == "media":
        data = _request("GET", f"/media/{a.n}", params={"project": PROJECT}, raw=True)
        with open(a.out, "wb") as fh:
            fh.write(data)
        print(f"saved {len(data)} bytes to {a.out}")
    elif a.cmd == "post":
        _post(a)
    elif a.cmd == "pair":
        r = _request("POST", "/pair", body={"phone": a.phone})
        print(f"Pairing code: {r['code']}\n{r['how']}")


if __name__ == "__main__":
    main()
