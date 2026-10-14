#!/usr/bin/env python3
"""chat_image -- draw a WhatsApp-style conversation (or before/after pair) as a PNG.

For showing the team what a change looks like on the phone, e.g. before and
after a reply-wording fix. Standard library + any Chromium/Chrome binary; no
Python packages.

Input JSON (a file, or - for stdin), either one conversation:
  {"title": "Material delivery", "messages": [
     {"from": "user", "text": "50 bags cement arrived"},
     {"from": "bot",  "text": "*Confirm this record?* ...", "buttons": ["Yes", "No"]}]}
or panels side by side:
  {"panels": [{"title": "Before", "messages": [...]}, {"title": "After", "messages": [...]}]}

`from` is "user" (green, right) or "bot" (white, left). WhatsApp *bold* and
_italic_ are rendered; "buttons" / "list" show as tappable rows under a message.

Usage:
  python3 teammate/chat_image.py convo.json out.png [--width 420]
Chromium: $CHROMIUM_PATH, else chromium/google-chrome on PATH, else /opt/pw-browsers/chromium.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #ffffff; font-family: -apple-system, 'Segoe UI', Roboto, 'Noto Sans', sans-serif; }
.row { display: flex; gap: 16px; padding: 16px; align-items: flex-start; }
.phone { flex: 0 0 auto; border-radius: 14px; overflow: hidden; border: 1px solid #d1d7db; }
.head { background: #008069; color: #fff; padding: 12px 14px; font-weight: 600; font-size: 15px; }
.chat { background: #efeae2; padding: 10px 10px 14px; display: flex; flex-direction: column; gap: 6px; }
.msg { max-width: 85%; padding: 6px 9px 7px; border-radius: 8px; font-size: 14.2px; line-height: 1.35;
       color: #111b21; white-space: pre-wrap; word-wrap: break-word; box-shadow: 0 1px 0.5px rgba(11,20,26,.13); }
.user { align-self: flex-end; background: #d9fdd3; }
.bot { align-self: flex-start; background: #ffffff; }
.opts { align-self: flex-start; max-width: 85%; display: flex; flex-direction: column; gap: 3px; margin-top: -3px; }
.opt { background: #fff; color: #027eb5; text-align: center; padding: 8px 12px; border-radius: 8px; font-size: 14px;
       box-shadow: 0 1px 0.5px rgba(11,20,26,.13); }
.note { align-self: center; background: #fff5c4; color: #54656f; font-size: 12.5px; padding: 4px 10px; border-radius: 7px; }
"""


def _format(text: str) -> str:
    out = html.escape(text or "")
    out = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", out)
    return out


def _panel(panel: dict, width: int) -> str:
    rows = []
    for m in panel.get("messages", []):
        who = m.get("from", "bot")
        if who == "note":
            rows.append(f'<div class="note">{_format(m.get("text", ""))}</div>')
            continue
        rows.append(
            f'<div class="msg {"user" if who == "user" else "bot"}">{_format(m.get("text", ""))}</div>'
        )
        options = m.get("buttons") or m.get("list") or []
        if options:
            opts = "".join(f'<div class="opt">{html.escape(str(o))}</div>' for o in options)
            rows.append(f'<div class="opts">{opts}</div>')
    title = html.escape(panel.get("title") or "Mesiri")
    return f'<div class="phone" style="width:{width}px"><div class="head">{title}</div><div class="chat">{"".join(rows)}</div></div>'


def build_html(spec: dict, width: int) -> str:
    panels = spec.get("panels") or [spec]
    body = "".join(_panel(p, width) for p in panels)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='row' id='root'>{body}</div></body></html>"


def _chromium() -> str:
    for candidate in (
        os.environ.get("CHROMIUM_PATH"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        "/opt/pw-browsers/chromium",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("no Chromium found; set CHROMIUM_PATH")


def render(spec: dict, out: str, width: int = 420) -> None:
    chrome = _chromium()
    panels = len(spec.get("panels") or [spec])
    page_width = panels * width + (panels + 1) * 16 + 2
    flags = [
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=2",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "chat.html"
        # Pass 1: let the page report its own height, so the image is cropped to fit.
        page.write_text(
            build_html(spec, width).replace(
                "</body>",
                "<script>document.title='H'+document.getElementById('root').scrollHeight</script></body>",
            ),
            encoding="utf-8",
        )
        dom = subprocess.run(
            [chrome, *flags, f"--window-size={page_width},4000", "--dump-dom", page.as_uri()],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        match = re.search(r"<title>H(\d+)</title>", dom)
        # Headless Chromium paints a viewport ~90px shorter than the window it
        # is given; the margin keeps the bottom of the tallest panel in frame.
        height = (int(match.group(1)) if match else 1200) + 120
        # Pass 2: the screenshot at that height.
        page.write_text(build_html(spec, width), encoding="utf-8")
        result = subprocess.run(
            [
                chrome,
                *flags,
                f"--window-size={page_width},{height}",
                f"--screenshot={Path(out).resolve()}",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not Path(out).exists():
            sys.exit(f"Chromium failed: {result.stderr[-500:]}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("spec", help="JSON file, or - for stdin")
    p.add_argument("out", help="PNG to write")
    p.add_argument("--width", type=int, default=420, help="width of one phone panel in CSS px")
    a = p.parse_args()
    spec = json.load(sys.stdin if a.spec == "-" else open(a.spec, encoding="utf-8"))
    render(spec, a.out, a.width)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
