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
  label <chat> team|customer|ignore|assistant-test|unlabelled [--project P]
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
  item note <id> "<step>"             a progress note (the bot reads these as heartbeats, request 139)
  item done <id> --ref R [--note N]   mark it done; R = commit / PR, e.g. aprodac/MERCON#262
  item wontdo <id> --note N           close it without doing it, with the reason
  summary <chat>                      one group on a page: open and done requests
  translate <n>                       transcript + English of a voice note / Malayalam message,
                                      on request (Gemini), with what it cost in rupees
  cost                                Gemini spend today and this month, in rupees
  allow <phone> [--name N] [--role owner|member]   approve someone to tag the bot (TM-03);
                                      owners can then approve others from the team group
  disallow <phone>                    remove an approval
  allowed                             who is approved (this project, or all)
  pair <phone-with-country-code>      link the spare number (prints a code to type on the phone)
  test [text] [--choose N|TITLE] [--wait 90]
                                      message the Mesiri assistant's test chat (assistant-test) as a
                                      worker, or tap an option of its latest menu, and print its replies
  post [text] [--text-file F] [--image FILE[::caption] ...] [--chat X]
                                      post into the TEAM group (customer groups are refused)

Messages are numbered (#1432). Refer to them by number when asking for a fix.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
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


def _test(a: argparse.Namespace) -> None:
    """Message the assistant-test chat (or tap its latest menu) and print the replies (TM-12)."""
    import time

    if not a.text and a.choose is None:
        sys.exit("give the text to send, or --choose N|TITLE")
    chats = _request("GET", "/chats", params={"project": PROJECT})["chats"]
    tests = [
        c
        for c in chats
        if c["role"] == "assistant-test" and (not PROJECT or c.get("project") == PROJECT)
    ]
    if not tests:
        sys.exit(
            "no chat is labelled assistant-test for this project: message the Mesiri assistant from the"
            " linked number once, then `inbox.py label <jid> assistant-test`"
        )
    jid = tests[0]["jid"]
    body: dict = {"chat": jid, "project": PROJECT}
    if a.choose is not None:
        recent = _request(
            "GET", "/messages", params={"chat": jid, "project": PROJECT, "limit": 50}
        )["messages"]
        menus = sorted(
            (m for m in recent if not m.get("from_me") and m.get("options")), key=lambda m: m["n"]
        )
        if not menus:
            sys.exit("the assistant hasn't sent a menu or buttons recently; send text first")
        option = int(a.choose) if a.choose.isdigit() else a.choose
        body["choose"] = {"message_n": menus[-1]["n"], "option": option}
        print(f"> tap {a.choose!r} on #{menus[-1]['n']}")
    else:
        body["text"] = a.text
        print(f"> {a.text}")
    started = _since(seconds=2)  # WhatsApp stamps whole seconds
    t0 = time.monotonic()
    _request("POST", "/send", body=body)
    seen: dict[int, dict] = {}
    last_new = None
    while time.monotonic() - t0 < a.wait:
        time.sleep(3)
        msgs = _request(
            "GET",
            "/messages",
            params={"chat": jid, "project": PROJECT, "since": started, "limit": 50},
        )["messages"]
        for m in msgs:
            if not m.get("from_me") and m["n"] not in seen:
                seen[m["n"]] = m
                last_new = time.monotonic()
                print(f"  [{last_new - t0:5.1f}s] {_line(m, with_chat=False)}")
        if last_new and time.monotonic() - last_new > 12:
            break
    if not seen:
        print(f"(no reply within {a.wait} s)")


def _item_line(i: dict) -> str:
    src = f"  (from #{i['source'].replace(',', ', #')})" if i.get("source") else ""
    ref = f"  → {i['done_ref']}" if i.get("done_ref") else ""
    status = _STATUS_MARK.get(i["status"], i["status"])
    held = f"  · {i['claimed_by']} on it" if i.get("claimed_by") and i["status"] in ("open", "in_progress") else ""
    return f"[{i['id']:>3}] {status:<14} {i['type']:<9} {i['title']}{src}{ref}{held}"


#: Who claims a request from here (TM-50): a person can set TEAMMATE_WORKER; a Claude Code session names itself.
_WORKER = os.environ.get("TEAMMATE_WORKER") or (
    f"Claude Code session {os.environ['CLAUDE_CODE_SESSION_ID'][-8:]}" if os.environ.get("CLAUDE_CODE_SESSION_ID") else "Claude Code"
)


def _session_url() -> str | None:
    """TM-77: this Claude Code session's claude.ai link, when it runs in the cloud (cse_X -> session_X)."""
    sdk = os.environ.get("CLAUDE_CODE_REMOTE_SDK_URL") or ""
    tail = sdk.rstrip("/").rsplit("/", 1)[-1]
    return f"https://claude.ai/code/session_{tail[4:]}" if tail.startswith("cse_") and len(tail) > 8 else None


#: TM-77: which Claude account this session runs on, as the team names it (e.g. "B (ilan-work)"); optional.
_ACCOUNT = os.environ.get("TEAMMATE_CLAUDE_ACCOUNT") or None


def _usage_body(a: argparse.Namespace) -> dict | None:
    """TM-79: the usage flags of `item usage` / `item done`, or None when none was given."""
    body = {"cost_usd": a.cost, "tokens": a.tokens, "pct_5h": a.pct5, "pct_7d": a.pct7}
    if all(v is None for v in body.values()):
        return None
    return {**body, "account": a.account or _ACCOUNT, "by": _WORKER, "project": PROJECT}


_WORD = re.compile(r"[a-z0-9]{4,}")
_STOP = {"with", "that", "this", "from", "when", "what", "still", "after", "before", "never", "always", "their", "into", "only", "gets", "says"}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _possible_repeats(title: str, items: list[dict]) -> list[dict]:
    """TM-83: open requests (and ones from the last 24 h) that may be the same problem: a [n] it names that is still
    open or has an open follow-up, or most of the same words. The bot's planner gets the same check (same.js)."""
    import datetime as dt

    day_ago = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
    live = [i for i in items if i["status"] in ("open", "in_progress") or (i["status"] == "done" and i["updated_at"] >= day_ago)]
    refs = {int(n) for n in re.findall(r"\[(\d+)\]", title)}
    words = _words(title)
    out = []
    for i in live:
        named = i["id"] in refs or any(f"[{n}]" in i["title"] for n in refs)
        theirs = _words(i["title"])
        overlap = len(words & theirs) / max(1, len(words | theirs))
        if (named and i["status"] in ("open", "in_progress")) or overlap >= 0.4:
            out.append(i)
    return out[:8]


def _item(a: argparse.Namespace) -> None:
    if a.action == "add":
        if len(a.args) < 2 or not a.type:
            sys.exit('usage: item add <chat> "<title>" --type bug|feature|question|complaint|task')
        title = " ".join(a.args[1:])
        if a.same_as:
            # TM-83: the same problem goes on the request that has it, never a second request (or a second fix).
            note = f"same problem reported again (via {_WORKER}): {title}"
            i = _request("POST", f"/items/{a.same_as}", body={"note": note, "project": PROJECT})["item"]
            print(f"added to {_item_line(i)}  (no new request)")
            return
        if not a.new:
            repeats = _possible_repeats(title, _request("GET", "/items", params={"project": PROJECT})["items"])
            if repeats:
                print("These open / recent requests may be the same problem:")
                for i in repeats:
                    print(f"  {_item_line(i)}")
                sys.exit('Same problem: item add ... --same-as <n> (adds it there; no second request). '
                         'Different: item add ... --new "<what makes it different>".')
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
    if a.action == "note":
        text = a.note or " ".join(a.args[1:])
        if not a.args or not a.args[0].isdigit() or not text.strip():
            sys.exit('usage: item note <id> "<what you are doing>"')
        i = _request("POST", f"/items/{a.args[0]}", body={"note": text.strip(), "project": PROJECT})["item"]
        print(_item_line(i))
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
    if a.action == "usage":
        body = _usage_body(a)
        if not body:
            sys.exit("usage: item usage <id> [--cost USD] [--pct5 N] [--pct7 N] [--tokens N] [--account B]")
        i = _request("POST", f"/items/{n}/usage", body=body)["item"]
        print(f"{_item_line(i)}  · Claude usage so far: ${i.get('usage_usd') or 0} · 5-hour {i.get('usage_5h') or '?'}% · weekly {i.get('usage_7d') or '?'}%")
        return
    if a.action in ("claim", "start"):
        # TM-50: one worker per request. A Claude Code session claims before it works on something; the team bot does
        # the same before it builds. Someone else holding it stops here and names them.
        try:
            held = _request("POST", f"/items/{n}/claim", body={"by": _WORKER, "take": a.take, "project": PROJECT})["item"]
        except SystemExit as e:
            sys.exit(f"[{n}] is already being worked on: {e}. Add to it with `item note {n} ...`, or --take if they stopped.")
        if a.action == "claim":
            print(f"{_item_line(held)}  · claimed by {held.get('claimed_by')}")
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
    if a.action == "done" and _usage_body(a):
        _request("POST", f"/items/{n}/usage", body=_usage_body(a))
    note = a.note
    if a.action == "start":
        # TM-77: who is on it, where to watch it, and on which Claude account: visible on the board and @bot status.
        where = [f"started by {_WORKER}", _session_url(), f"account {a.account or _ACCOUNT}" if (a.account or _ACCOUNT) else None]
        note = " · ".join([x for x in [note, *where] if x])
    body = {**change, "ref": a.ref, "note": note, "project": PROJECT}
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
    lab.add_argument("role", choices=["team", "customer", "ignore", "assistant-test", "unlabelled"])
    lab.add_argument("--project", default=PROJECT, help="default: TEAMMATE_PROJECT")
    rec = sub.add_parser("recent")
    rec.add_argument("--chat")
    rec.add_argument("--role", choices=["team", "customer", "assistant-test", "unlabelled"])
    rec.add_argument("--hours", type=float, default=24)
    rec.add_argument("--limit", type=int, default=100)
    sea = sub.add_parser("search")
    sea.add_argument("words", nargs="+")
    sea.add_argument("--chat")
    sea.add_argument("--role", choices=["team", "customer", "assistant-test", "unlabelled"])
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
    itm.add_argument("action", choices=["show", "add", "start", "claim", "note", "usage", "done", "wontdo"])
    itm.add_argument("--take", action="store_true", help="claim it even though someone else holds it (say why in a note)")
    itm.add_argument("args", nargs="*")
    itm.add_argument("--type", choices=["bug", "feature", "question", "complaint", "task"])
    itm.add_argument("--from", dest="source", help="message numbers, e.g. 6,7")
    itm.add_argument("--summary")
    itm.add_argument("--ref", help="commit or PR, e.g. aprodac/MERCON#262")
    itm.add_argument("--note")
    # TM-83: item add checks for a request that already has this problem.
    itm.add_argument("--same-as", type=int, help="add it to this request instead of a new one")
    itm.add_argument("--new", help="it is not a repeat of the requests listed: why (one line)")
    # TM-79: what this session used of Claude for the request (from /usage or /cost), on `usage` or `done`.
    itm.add_argument("--cost", type=float, help="dollars this session spent on it (Claude Code's /cost)")
    itm.add_argument("--pct5", type=float, help="percent of the 5-hour window it took (from /usage before and after)")
    itm.add_argument("--pct7", type=float, help="percent of the weekly window it took")
    itm.add_argument("--tokens", type=int)
    itm.add_argument("--account", help='the Claude account, e.g. "B (ilan-work)" (default: TEAMMATE_CLAUDE_ACCOUNT)')
    sm = sub.add_parser("summary")
    sm.add_argument("chat")
    trn = sub.add_parser("translate")
    trn.add_argument("n", type=int)
    sub.add_parser("cost")
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
    tst = sub.add_parser("test")
    tst.add_argument("text", nargs="?")
    tst.add_argument("--choose", help="tap an option of the latest menu: its number or exact title")
    tst.add_argument("--wait", type=float, default=90)
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
    elif a.cmd == "test":
        _test(a)
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
    elif a.cmd == "translate":
        r = _request("POST", f"/messages/{a.n}/translate?project={PROJECT or ''}", timeout=120)
        print(f"#{r['n']} ({r.get('language') or '?'})")
        if r.get("transcript"):
            print(f"  said: {r['transcript']}")
        if r.get("translation"):
            print(f"  EN:   {r['translation']}")
        c = r.get("cost")
        if c:
            print(
                f"  cost: Rs {c['inr']:.2f} ({c['input_tokens']} in / {c['output_tokens']} out tokens, {c['model']})"
            )
        else:
            print("  cost: already translated before, no new cost")
    elif a.cmd == "cost":
        u = _request("GET", "/ai/usage", params={"project": PROJECT})
        for label in ("today", "month"):
            x = u[label]
            print(
                f"{label:<6} Rs {x['inr']:.2f}  ({x['calls']} calls, {x['input_tokens']} in / {x['output_tokens']} out tokens)"
            )
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
