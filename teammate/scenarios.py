#!/usr/bin/env python3
"""scenarios -- run WhatsApp scenarios against the REAL Mesiri assistant (WA-80).

Each scenario of a catalogue (default: apps/whatsapp-assistant/tests/live/scenarios_27oct.json)
is a list of steps sent to the assistant-test chat through the teammate listener, exactly as
`inbox.py test` does: a message, or a tap on a button of the assistant's last reply. Every
check is tied to a mark of the 27 Oct live rounds (M01..M58). A mark passes only when every
check of it passed in every run (`--repeat 3` is the done-gate: the real model varies).

Standard library only (as inbox.py). Environment: TEAMMATE_TOKEN, TEAMMATE_PROJECT (see inbox.py).

  scenarios.py --check                    validate the catalogue (no network): every mark checked
  scenarios.py [--only S01,S04] [--repeat 3] [--json out.json]

Step keys:  send | tap (title prefix; the step fails without it) | tap_if (tap only when offered)
            | if_last_re (run the step only when the last replies match) | capture {var: regex}
            | checks [...]. A step with only checks re-checks the last replies.
Check keys: mark, has, lacks, has_re, lacks_re (on the reply text, case-insensitive),
            buttons_has (title prefixes), buttons_lacks_re, body_count_max {text: n},
            no_duplicate_lines, max_seconds (first reply), observe ("kinds": recorded, not judged).
            "{NAME}" is a catalogue pattern, "{var}" a captured value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FILE = HERE.parent / "apps" / "whatsapp-assistant" / "tests" / "live" / "scenarios_27oct.json"
CHECK_KEYS = {
    "mark", "has", "lacks", "has_re", "lacks_re", "buttons_has", "buttons_lacks_re",
    "body_count_max", "no_duplicate_lines", "max_seconds", "observe",
}
STEP_KEYS = {"send", "send_image", "send_voice", "tap", "tap_if", "if_last_re", "capture", "checks", "expect_card"}
_ACTIONS = ("send", "send_image", "send_voice", "tap", "tap_if")
_OPTION_LINE = re.compile(r"^\s*\d+\)\s")
#: The assistant refuses every message once the company's daily trial limit is reached:
#: nothing after that measures anything (the 27 Oct baseline ran into it at S09).
_REFUSED = re.compile(r"free-trial limit|trial limit", re.I)


class Refused(Exception):
    """The assistant stopped reading messages (the trial limit): the run cannot go on."""


# -- the catalogue -----------------------------------------------------------------------------


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        cat = json.load(fh)
    cat["_dir"] = str(path.parent)  # media files are named relative to the catalogue
    return cat


def validate(cat: dict) -> list[str]:
    """Problems with the catalogue: unknown keys, marks never checked, checks of unknown marks."""
    problems: list[str] = []
    marks = set(cat.get("marks") or {})
    checked: set[str] = set()
    ids: set[str] = set()
    for sc in cat.get("scenarios") or []:
        if sc["id"] in ids:
            problems.append(f"{sc['id']}: duplicate id")
        ids.add(sc["id"])
        for n, step in enumerate([*sc.get("steps", []), *sc.get("cleanup", [])], 1):
            where = f"{sc['id']} step {n}"
            if set(step) - STEP_KEYS:
                problems.append(f"{where}: unknown keys {sorted(set(step) - STEP_KEYS)}")
            if sum(k in step for k in _ACTIONS) > 1:
                problems.append(f"{where}: one of {' / '.join(_ACTIONS)}")
            for key in ("send_image", "send_voice"):
                if key in step and not (Path(cat.get("_dir", ".")) / step[key]["file"]).is_file():
                    problems.append(f"{where}: no file {step[key]['file']}")
            for check in step.get("checks", []):
                if set(check) - CHECK_KEYS:
                    problems.append(f"{where}: unknown check keys {sorted(set(check) - CHECK_KEYS)}")
                mark = check.get("mark")
                if mark not in marks:
                    problems.append(f"{where}: unknown mark {mark!r}")
                checked.add(mark)
                for rx in [*check.get("has_re", []), *check.get("lacks_re", []), *check.get("buttons_lacks_re", [])]:
                    try:
                        re.compile(_expand(rx, cat.get("patterns") or {}, {}, strict=False))
                    except re.error as err:
                        problems.append(f"{where}: bad regex {rx!r}: {err}")
    for mark in sorted(marks - checked):
        problems.append(f"{mark}: no check covers it")
    return problems


def _expand(text: str, patterns: dict, vars_: dict, *, strict: bool = True) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name in patterns:
            return patterns[name]
        if name in vars_:
            return re.escape(str(vars_[name]))
        if strict:
            raise KeyError(name)
        return "0"

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, text)


# -- talking to the assistant ------------------------------------------------------------------


class Chat:
    """The assistant-test chat, through the teammate listener (inbox.py's API)."""

    def __init__(self, quiet: float, wait: float) -> None:
        sys.path.insert(0, str(HERE))
        import inbox  # noqa: PLC0415 -- stdlib-only sibling

        self.inbox = inbox
        self.quiet, self.wait = quiet, wait
        chats = inbox._request("GET", "/chats", params={"project": inbox.PROJECT})["chats"]
        tests = [c for c in chats if c["role"] == "assistant-test" and (not inbox.PROJECT or c.get("project") == inbox.PROJECT)]
        if not tests:
            sys.exit("no chat is labelled assistant-test for this project")
        self.jid = tests[0]["jid"]

    def act(
        self, *, text: str | None = None, choose: dict | None = None, media: dict | None = None
    ) -> tuple[list[dict], float | None]:
        """Send, then collect the assistant's replies until it has been quiet for a while.
        ``media``: {"image_base64", "caption"} or {"audio_base64", "audio_mime"} (the
        listener's /send, assistant-test chat only)."""
        body: dict = {"chat": self.jid, "project": self.inbox.PROJECT}
        if choose is not None:
            body["choose"] = choose
        elif media is not None:
            body.update(media)
        else:
            body["text"] = text
        started = self.inbox._since(seconds=2)  # WhatsApp stamps whole seconds
        t0 = time.monotonic()
        self.inbox._request("POST", "/send", body=body)
        seen: dict[int, dict] = {}
        first = last = None
        while time.monotonic() - t0 < self.wait:
            time.sleep(2)
            msgs = self.inbox._request(
                "GET", "/messages", params={"chat": self.jid, "project": self.inbox.PROJECT, "since": started, "limit": 50}
            )["messages"]
            for m in msgs:
                if not m.get("from_me") and m["n"] not in seen:
                    seen[m["n"]] = m
                    last = time.monotonic()
                    first = first if first is not None else last - t0
            if last is not None and time.monotonic() - last > self.quiet:
                break
        return sorted(seen.values(), key=lambda m: m["n"]), first


# -- one run -----------------------------------------------------------------------------------


def _text(replies: list[dict]) -> str:
    return "\n".join(m.get("text") or "" for m in replies)


def _body_lines(replies: list[dict]) -> list[str]:
    return [ln.strip() for ln in _text(replies).splitlines() if ln.strip() and not _OPTION_LINE.match(ln)]


def _buttons(replies: list[dict]) -> list[dict]:
    return [{**o, "message_n": m["n"]} for m in replies for o in (m.get("options") or [])]


def _find_option(replies: list[dict], title: str) -> dict | None:
    want = title.casefold()
    options = _buttons(replies)
    return next((o for o in options if o["title"].casefold() == want), None) or next(
        (o for o in options if o["title"].casefold().startswith(want)), None
    )


def judge(check: dict, replies: list[dict], seconds: float | None, patterns: dict, vars_: dict) -> tuple[bool | None, str]:
    """(passed, why). None: observed only, or the check could not be evaluated."""
    text = _text(replies).casefold()
    try:
        for s in check.get("has", []):
            if _expand(s, patterns, vars_).casefold() not in text:
                return False, f"missing {s!r}"
        for s in check.get("lacks", []):
            if _expand(s, patterns, vars_).casefold() in text:
                return False, f"has {s!r}"
        for rx in check.get("has_re", []):
            if not re.search(_expand(rx, patterns, vars_), text, re.I | re.S):
                return False, f"no match /{rx}/"
        for rx in check.get("lacks_re", []):
            if re.search(_expand(rx, patterns, vars_), text, re.I | re.S):
                return False, f"matches /{rx}/"
    except KeyError as missing:
        return None, f"not evaluated: nothing captured for {missing}"
    titles = [o["title"] for o in _buttons(replies)]
    for want in check.get("buttons_has", []):
        if not any(t.casefold().startswith(want.casefold()) for t in titles):
            return False, f"no button {want!r} (buttons: {titles})"
    for rx in check.get("buttons_lacks_re", []):
        if any(re.search(rx, t, re.I) for t in titles):
            return False, f"a button matches /{rx}/ ({titles})"
    body = _body_lines(replies)
    for needle, most in (check.get("body_count_max") or {}).items():
        count = sum(ln.casefold().count(needle.casefold()) for ln in body)
        if count > most:
            return False, f"{needle!r} {count}x (max {most})"
    if check.get("no_duplicate_lines"):
        dupes = sorted({ln for ln in body if body.count(ln) > 1})
        if dupes:
            return False, f"repeated lines {dupes}"
    if "max_seconds" in check:
        if seconds is None:
            return False, "no reply"
        if seconds > check["max_seconds"]:
            return False, f"first reply {seconds:.1f} s (max {check['max_seconds']} s)"
    if check.get("observe"):
        return None, "observed: " + ", ".join(sorted({m.get("kind", "?") for m in replies}))
    return True, ""


def run_scenario(chat: Chat, cat: dict, sc: dict, log: list[str]) -> list[dict]:
    patterns = cat.get("patterns") or {}
    vars_: dict = {}
    results: list[dict] = []
    last: list[dict] = []
    last_seconds: float | None = None
    broken = ""

    def do(step: dict, n: int, *, cleanup: bool = False) -> None:
        nonlocal last, last_seconds, broken
        checks = step.get("checks", [])
        if broken and not cleanup:
            for c in checks:
                results.append({"scenario": sc["id"], "step": n, "mark": c["mark"], "ok": False, "why": f"blocked: {broken}"})
            return
        if "if_last_re" in step and not re.search(_expand(step["if_last_re"], patterns, vars_, strict=False), _text(last), re.I):
            log.append(f"  {n:>2}. (skipped: last replies don't match /{step['if_last_re']}/)")
            for c in checks:
                results.append({"scenario": sc["id"], "step": n, "mark": c["mark"], "ok": None, "why": "condition not met"})
            return
        if "send" in step:
            log.append(f"  {n:>2}. > {step['send']}")
            last, last_seconds = chat.act(text=step["send"])
        elif "send_image" in step or "send_voice" in step:
            import base64

            media = step.get("send_image") or step.get("send_voice")
            raw = base64.b64encode((Path(cat.get("_dir", ".")) / media["file"]).read_bytes()).decode()
            if "send_image" in step:
                payload = {"image_base64": raw, "caption": media.get("caption") or ""}
            else:
                payload = {"audio_base64": raw, "audio_mime": media.get("mime") or "audio/ogg; codecs=opus"}
            log.append(f"  {n:>2}. > [{'image' if 'send_image' in step else 'voice'}] {media['file']}")
            last, last_seconds = chat.act(media=payload)
        elif "tap" in step or "tap_if" in step:
            title = step.get("tap") or step.get("tap_if")
            option = _find_option(last, title)
            if option is None:
                if "tap" in step and not cleanup:
                    broken = f"no {title!r} button at step {n}"
                    log.append(f"  {n:>2}. ✗ tap {title!r}: not offered")
                    for c in checks:
                        results.append({"scenario": sc["id"], "step": n, "mark": c["mark"], "ok": False, "why": broken})
                    return
                log.append(f"  {n:>2}. (no {title!r} to tap)")
                return
            log.append(f"  {n:>2}. > tap {option['title']!r}")
            last, last_seconds = chat.act(choose={"message_n": option["message_n"], "option": option["n"]})
        acted = any(k in step for k in _ACTIONS)
        for m in last if acted else []:
            shown = (m.get("text") or "").replace("\n", " ⏎ ")
            log.append(f"      < [{m.get('kind')}] {shown}")
        if acted and last_seconds is not None:
            log.append(f"      (first reply {last_seconds:.1f} s)")
        if acted and not last:
            log.append("      (no reply)")
        if _REFUSED.search(_text(last)):
            raise Refused(f"{sc['id']} step {n}: the assistant refused it (trial limit)")
        for var, rx in (step.get("capture") or {}).items():
            found = re.search(rx, _text(last), re.I)
            if found:
                vars_[var] = found.group(1)
                log.append(f"      captured {var} = {vars_[var]}")
        for c in checks:
            ok, why = judge(c, last, last_seconds, patterns, vars_)
            results.append({"scenario": sc["id"], "step": n, "mark": c["mark"], "ok": ok, "why": why})
            log.append(f"      {'✓' if ok else '·' if ok is None else '✗'} {c['mark']} {why}".rstrip())

    log.append(f"\n== {sc['id']} {sc.get('title', '')}")
    done = 0
    try:
        for n, step in enumerate(cat.get("reset") or [], 1):
            do(step, n, cleanup=True)
        last = []
        for n, step in enumerate(sc.get("steps", []), 1):
            done = n
            do(step, n)
        for n, step in enumerate(sc.get("cleanup", []), 1):
            do(step, 100 + n, cleanup=True)
    except Refused as why:
        log.append(f"  !! {why}: the rest is not run")
        judged = {(r["step"], r["mark"]) for r in results}
        for n, step in enumerate(sc.get("steps", []), 1):
            for c in step.get("checks", []):
                if n >= done and (n, c["mark"]) not in judged:
                    results.append({"scenario": sc["id"], "step": n, "mark": c["mark"], "ok": None, "why": str(why)})
        # A check judged on the refusal itself measured nothing either.
        for r in results:
            if r["scenario"] == sc["id"] and r["step"] == done and r["ok"] is not None:
                r["ok"], r["why"] = None, str(why)
        why.results = results  # type: ignore[attr-defined]
        raise
    return results


def summarise(cat: dict, runs: list[list[dict]]) -> tuple[str, int]:
    """Per mark: PASS only when every check of it passed in every run."""
    marks = cat["marks"]
    lines = ["", "| Mark | Shot | Group | Result | Runs passed | First failure |", "|---|---|---|---|---|---|"]
    failing = 0
    for mark, info in marks.items():
        per_run = []
        why = ""
        for results in runs:
            mine = [r for r in results if r["mark"] == mark]
            judged = [r for r in mine if r["ok"] is not None]
            if not judged:
                per_run.append(None)
                why = why or next((r["why"] for r in mine), "not reached")
                continue
            bad = [r for r in judged if not r["ok"]]
            per_run.append(not bad)
            if bad and not why:
                why = f"{bad[0]['scenario']} step {bad[0]['step']}: {bad[0]['why']}"
        judged_runs = [p for p in per_run if p is not None]
        if not judged_runs:
            result = "n/a"
        elif all(judged_runs) and len(judged_runs) == len(runs):
            result = "PASS"
        else:
            result = "FAIL"
            failing += 1
        passed = f"{sum(1 for p in per_run if p)}/{len(runs)}"
        lines.append(f"| {mark} | {info.get('shot', '')} | {info.get('group', '')}{' ' + info['w'] if info.get('w') else ''} "
                     f"| {result} | {passed} | {why.replace('|', '/')[:140]} |")
    return "\n".join(lines), failing


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--only", help="scenario ids, comma separated")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--quiet", type=float, default=10, help="seconds of silence that end a reply")
    ap.add_argument("--wait", type=float, default=75, help="most seconds to wait for a reply")
    ap.add_argument("--json", type=Path, help="write every check result here")
    ap.add_argument("--check", action="store_true", help="validate the catalogue and stop (no network)")
    a = ap.parse_args()

    cat = load(a.file)
    problems = validate(cat)
    if problems:
        print("Catalogue problems:\n  " + "\n  ".join(problems))
        sys.exit(2)
    scenarios = cat["scenarios"]
    if a.only:
        wanted = {s.strip().upper() for s in a.only.split(",") if s.strip()}
        scenarios = [s for s in scenarios if s["id"].upper() in wanted]
        if not scenarios:
            sys.exit(f"no scenario among {sorted(wanted)}")
    if a.check:
        steps = sum(len(s.get("steps", [])) for s in scenarios)
        print(f"OK: {len(cat['marks'])} marks, {len(scenarios)} scenarios, {steps} steps; every mark is checked.")
        return
    if not os.environ.get("TEAMMATE_TOKEN"):
        sys.exit("TEAMMATE_TOKEN is not set")

    chat = Chat(quiet=a.quiet, wait=a.wait)
    runs: list[list[dict]] = []
    for run in range(1, a.repeat + 1):
        log: list[str] = [f"\n#### Run {run} of {a.repeat}"]
        results: list[dict] = []
        refused = None
        for sc in scenarios:
            if refused is not None:
                results += [{"scenario": sc["id"], "step": n, "mark": c["mark"], "ok": None, "why": refused}
                            for n, step in enumerate(sc.get("steps", []), 1) for c in step.get("checks", [])]
                continue
            mine: list[dict] = []
            try:
                mine = run_scenario(chat, cat, sc, log)
            except Refused as why:
                refused = str(why)
                mine = [r for r in getattr(why, "results", [])]
            results += mine
            print("\n".join(log), flush=True)
            log = []
        runs.append(results)
        if refused is not None:
            print(f"\n!! Stopped: {refused}. Marks not reached are n/a, not passed.", flush=True)
            break
    if a.only:
        keep = {r["mark"] for results in runs for r in results}
        cat = {**cat, "marks": {k: v for k, v in cat["marks"].items() if k in keep}}
    table, failing = summarise(cat, runs)
    print(f"\n### Result: {len(cat['marks']) - failing} of {len(cat['marks'])} marks pass ({a.repeat} run(s))")
    print(table)
    if a.json:
        a.json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if failing else 0)


if __name__ == "__main__":
    main()
