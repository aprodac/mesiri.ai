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
  history <chat> [--pages 10]         pull a group's older messages from the spare phone
                                      (it must be online); 50 per request
  media <n> <out-file>                download a photo / voice note / document
  items [--chat X] [--status S] [--type T]
                                      what the groups asked for, and what was done (TM-08)
  item show <id>                      one request with its history
  item add <chat> <title> --type bug|feature|question|complaint|task [--from 6,7] [--summary S]
  item start <id> [--note N]          mark it in progress
  item done <id> --ref R [--note N]   mark it done; R = commit / PR, e.g. aprodac/MERCON#262
  item wontdo <id> --note N           close it without doing it, with the reason
  summary <chat>                      one group on a page: open and done requests
  allow <phone> [--name N] [--role owner|member]   approve someone to tag the bot (TM-03);
                                      owners can then approve others from the team group
  disallow <phone>                    remove an approval
  allowed                             who is approved (this project, or all)
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
    timeout: float = 60,
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    # TM-07: what a voice note says, and English for non-English messages.
    extra = ""
    if m.get("transcript"):
        extra += f' 🗣 "{m["transcript"]}"'
    if m.get("translation") and m.get("translation") != m.get("transcript"):
        extra += f"  ⇒ EN: {m['translation']}"
    if extra and m.get("language"):
        extra = f"  [{m['language']}]{extra}"
    extra = extra.replace(chr(10), " ⏎ ")
    return f"#{m['n']:<6} {_when(m['at'])}  {chat}{_who(m)}: {kind}{text}{quoted}{extra}"


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


_STATUS_MARK = {
    "open": "○ open",
    "in_progress": "◐ in progress",
    "done": "● done",
    "wont_do": "✕ won't do",
}


def _item_line(i: dict) -> str:
    src = f"  (from #{i['source'].replace(',', ', #')})" if i.get("source") else ""
    ref = f"  → {i['done_ref']}" if i.get("done_ref") else ""
    status = _STATUS_MARK.get(i["status"], i["status"])
    return f"[{i['id']:>3}] {status:<14} {i['type']:<9} {i['title']}{src}{ref}"


def _item(a: argparse.Namespace) -> None:
    if a.action == "add":
        if len(a.args) < 2 or not a.type:
            sys.exit('usage: item add <chat> "<title>" --type bug|feature|question|complaint|task')
        body = {
            "chat": a.args[0],
            "title": " ".join(a.args[1:]),
            "type": a.type,
            "summary": a.summary,
            "source": a.source,
            "project": PROJECT,
            "created_by": "claude-code",
        }
        i = _request("POST", "/items", body=body)["item"]
        print(f"logged {_item_line(i)}  in {i['chat_name']}")
        return
    if len(a.args) != 1 or not a.args[0].isdigit():
        sys.exit(f"usage: item {a.action} <id>")
    n = a.args[0]
    if a.action == "show":
        i = _request("GET", f"/items/{n}", params={"project": PROJECT})["item"]
        print(_item_line(i))
        print(f"  group: {i['chat_name']} ({i.get('project') or '-'})")
        if i.get("summary"):
            print(f"  summary: {i['summary']}")
        for entry in i.get("log", []):
            bits = [entry.get("status") or "", entry.get("ref") or "", entry.get("note") or ""]
            print(f"  {_when(entry['at'])}  " + "  ".join(b for b in bits if b))
        return
    change = {
        "start": {"status": "in_progress"},
        "done": {"status": "done"},
        "wontdo": {"status": "wont_do"},
    }[a.action]
    if a.action == "done" and not a.ref:
        sys.exit("item done needs --ref (the commit or PR that did it)")
    if a.action == "wontdo" and not a.note:
        sys.exit("item wontdo needs --note (why)")
    body = {**change, "ref": a.ref, "note": a.note, "project": PROJECT}
    i = _request("POST", f"/items/{n}", body=body)["item"]
    print(_item_line(i))


def _summary(chat: str) -> None:
    items = _request("GET", "/items", params={"chat": chat, "project": PROJECT})["items"]
    chats = _request("GET", "/chats", params={"project": PROJECT})["chats"]
    hits = [c for c in chats if chat.lower() in (c.get("name") or "").lower() or c["jid"] == chat]
    for c in hits:
        print(
            f"{c.get('name')}  ({c['role']}, {c.get('project') or '-'}): {c['messages']} messages, "
            f"last {_when(c.get('last_message_at'))}"
        )
    for label, statuses in (("Open", ("open", "in_progress")), ("Done", ("done", "wont_do"))):
        group = [i for i in items if i["status"] in statuses]
        print()
        print(f"{label} ({len(group)})")
        for i in group:
            print("  " + _item_line(i))


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
    his = sub.add_parser("history")
    his.add_argument("chat")
    his.add_argument("--pages", type=int, default=10)
    his.add_argument("--count", type=int, default=50)
    med = sub.add_parser("media")
    med.add_argument("n", type=int)
    med.add_argument("out")
    its = sub.add_parser("items")
    its.add_argument("--chat")
    its.add_argument("--status", choices=["open", "in_progress", "done", "wont_do"])
    its.add_argument("--type", choices=["bug", "feature", "question", "complaint", "task"])
    itm = sub.add_parser("item")
    itm.add_argument("action", choices=["show", "add", "start", "done", "wontdo"])
    itm.add_argument("args", nargs="*")
    itm.add_argument("--type", choices=["bug", "feature", "question", "complaint", "task"])
    itm.add_argument("--from", dest="source", help="message numbers, e.g. 6,7")
    itm.add_argument("--summary")
    itm.add_argument("--ref", help="commit or PR, e.g. aprodac/MERCON#262")
    itm.add_argument("--note")
    sm = sub.add_parser("summary")
    sm.add_argument("chat")
    alw = sub.add_parser("allow")
    alw.add_argument("phone")
    alw.add_argument("--name")
    alw.add_argument("--role", choices=["owner", "member"], default="member")
    alw.add_argument("--project", default=PROJECT)
    dis = sub.add_parser("disallow")
    dis.add_argument("phone")
    dis.add_argument("--project", default=PROJECT)
    sub.add_parser("allowed")
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
        ai = h.get("ai") or {}
        if not ai.get("enabled"):
            print("Translation: off (no Gemini key on the listener)")
        else:
            state = {True: "working", False: "KEY CHECK FAILED", None: "checking"}[ai.get("ok")]
            print(f"Translation: {state} ({ai.get('model')}); {ai.get('pending', 0)} waiting")
            if ai.get("last_error"):
                print(f"  last error: {ai['last_error']}")
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
    elif a.cmd == "history":
        print("asking the phone for older messages (it must be online)...")
        total = 0
        for page in range(1, a.pages + 1):
            # One page per call keeps each request under the proxy's 60 s limit.
            body = {"chat": a.chat, "project": PROJECT, "pages": 1, "count": a.count}
            r = _request("POST", "/history", body=body, timeout=90)
            total += r["added"]
            print(
                f"  page {page}: {r['added']} older messages; oldest now {_when(r.get('oldest_at'))}"
            )
            if not r["added"]:
                break
        print(f"{r['chat']}: {total} older messages pulled")
    elif a.cmd == "media":
        data = _request("GET", f"/media/{a.n}", params={"project": PROJECT}, raw=True)
        with open(a.out, "wb") as fh:
            fh.write(data)
        print(f"saved {len(data)} bytes to {a.out}")
    elif a.cmd == "post":
        _post(a)
    elif a.cmd == "items":
        params = {"chat": a.chat, "status": a.status, "type": a.type, "project": PROJECT}
        items = _request("GET", "/items", params=params)["items"]
        if not items:
            print("(no requests logged)")
        for i in items:
            print(f"{_item_line(i)}  · {i['chat_name']}")
    elif a.cmd == "item":
        _item(a)
    elif a.cmd == "summary":
        _summary(a.chat)
    elif a.cmd in ("allow", "disallow"):
        if not a.project:
            sys.exit("say which project: --project mercon (or set TEAMMATE_PROJECT)")
        if a.cmd == "allow":
            body = {"project": a.project, "phone": a.phone, "name": a.name, "role": a.role}
            p = _request("POST", "/people", body=body)["person"]
            print(f"approved {p.get('name') or a.phone} as {p['role']} for {p['project']}")
        else:
            _request("POST", "/people/remove", body={"project": a.project, "phone": a.phone})
            print(f"removed {a.phone} from {a.project}")
    elif a.cmd == "allowed":
        people = _request("GET", "/people", params={"project": PROJECT})["people"]
        if not people:
            print("(nobody approved yet)")
        for p in people:
            num = (p.get("pn") or p.get("jid") or "").split("@")[0]
            print(
                f"{p['project']:<8} {p['role']:<7} {p.get('name') or '-':<16} …{num[-4:]}  added by {p.get('added_by') or '-'} {_when(p.get('added_at'))}"
            )
    elif a.cmd == "pair":
        r = _request("POST", "/pair", body={"phone": a.phone})
        print(f"Pairing code: {r['code']}\n{r['how']}")


if __name__ == "__main__":
    main()
