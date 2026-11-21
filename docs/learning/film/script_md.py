#!/usr/bin/env python3
"""The readable copy of an episode's script, for review: episode-NN.json -> scripts/episode-NN.md.

    python3 docs/learning/film/script_md.py 01

The JSON is the source (build.mjs films it); this page is made from it, never edited by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOWN = {"cards": ("title", "text"), "phases": ("name", "text"), "steps": ("module", "text"), "people": ("who", "worry"),
         "leaks": ("title", "eg"), "questions": ("text",), "segments": ("range", "label"), "lines": ("text",)}


def main(ep: str) -> None:
    ep = ep.zfill(2)
    script = json.loads((HERE / f"episode-{ep}.json").read_text(encoding="utf-8"))
    words = sum(len(b.split()) for s in script["scenes"] for b in s["beats"])
    out = [f"# Episode {script['episode']}: {script['title']}", "",
           f"> Made from `episode-{ep}.json` by `script_md.py`; edit the JSON, then run it again.", ""]
    for key in ("status", "objective"):
        if script.get(key):
            out += [f"**{key.capitalize()}:** {script[key]}", ""]
    out += [f"**Length:** {len(script['scenes'])} scenes, {words} words of narration (about {round(words / 150)} minutes)", ""]
    part = None
    for n, s in enumerate(script["scenes"], 1):
        if s.get("part") and s["part"] != part:
            part = s["part"]
            out += [f"## {part}", ""]
        where = f" · screen `{s['url']}`" if s.get("url") else ""
        out += [f"### {n}. {s['title']}", "", f"*{s['eyebrow']} · {s['kind']}{where}*", ""]
        shown = []
        for key, fields in SHOWN.items():
            for item in s.get(key, []):
                shown.append(" · ".join(str(item[f]) for f in fields if item.get(f)))
        for key in ("footer", "callout"):
            if s.get(key):
                shown.append(" · ".join(str(v) for k, v in s[key].items() if k != "at"))
        if s.get("note"):
            shown.append(s["note"])
        if shown:
            out += ["On screen:", "", *[f"- {x}" for x in shown], ""]
        if s.get("capture"):
            c = s["capture"]
            out += ["**Record (real reply):**", "",
                    f"- Via: {c['via']}, as {c['as']}, on day {c['day']}",
                    f"- Send: `{c['send']}`" + (f" (shown as {c['shown_as']})" if c.get("shown_as") else ""),
                    f"- Then: {c['tap']}", f"- {c['real']}", ""]
        if s.get("frames"):
            out += ["**Record (on the website, step by step):**", ""]
            for f in s["frames"]:
                bits = [f"beat {f['at'] + 1}"]
                if f.get("url"):
                    bits.append(f"open `{f['url']}`")
                if f.get("do"):
                    bits.append(f"do: {f['do']}")
                bits.append(f"picture: {f['show']}")
                if f.get("mark"):
                    bits.append(f"light: {f['mark']}")
                if f.get("note"):
                    bits.append(f"({f['note']})")
                out.append("- " + " · ".join(bits))
            out += ["", f"*{s['record']}*", ""] if s.get("record") else [""]
        out += ["Narration:", "", "\n>\n".join(f"> {b}" for b in s["beats"]), ""]
    target = HERE / "scripts" / f"episode-{ep}.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {target.relative_to(HERE)} ({words} words)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "01")
