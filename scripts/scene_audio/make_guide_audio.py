#!/usr/bin/env python3
"""UX-76: the walkthroughs' narrator, recorded once with ElevenLabs (asked 20 Nov 2026: "the old voice is bad, use
eleven lab voice"), the same voice as the sample company's scenes (George, make_scene_audio.py).

    node scripts/scene_audio/guide_lines.mjs              # the lines, as the browser sends them
    python3 scripts/scene_audio/make_guide_audio.py       # record what is missing, drop what is no longer said

Writes apps/dashboard/public/learn/voice/<id>.mp3 (id: the line's sha1, 12 hex) and apps/dashboard/src/lib/
guide-audio.gen.ts (each line and its file). lib/voice.ts plays the file when a step's words have one; any other
line (a step changed since, a hint) is read by the server's voice as before. Static files: the VPS needs no key.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import urllib.error
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LINES = HERE / "guide-lines.json"
OUT = ROOT / "apps/dashboard/public/learn/voice"
GEN = ROOT / "apps/dashboard/src/lib/guide-audio.gen.ts"

_spec = importlib.util.spec_from_file_location("make_scene_audio", HERE / "make_scene_audio.py")
scene = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scene)


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _under_1000(n: int) -> str:
    words = []
    if n >= 100:
        words.append(f"{_ONES[n // 100]} hundred")
        n %= 100
        if n:
            words.append("and")
    if n >= 20:
        words.append(_TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else ""))
    elif n or not words:
        words.append(_ONES[n])
    return " ".join(words)


def rupees_in_words(n: int) -> str:
    """82,06,050 -> 'eighty-two lakh, six thousand and fifty': how an Indian builder says a sum."""
    parts = []
    for size, name in ((10**7, "crore"), (10**5, "lakh"), (1000, "thousand")):
        if n >= size:
            parts.append(f"{rupees_in_words(n // size) if size == 10**7 else _under_1000(n // size)} {name}")
            n %= size
    if n and parts and n < 100:
        return ", ".join(parts) + f" and {_under_1000(n)}"
    if n:
        parts.append(_under_1000(n))
    return ", ".join(parts) if parts else "zero"


_SAY = [
    (re.compile(r"₹\s?(\d{1,3}(?:,\d{2,3})*)(?:\.(\d{1,2}))?"),
     lambda m: f"{rupees_in_words(int(m.group(1).replace(',', '')))} rupees"
               + (f" and {int(m.group(2))} paise" if m.group(2) and int(m.group(2)) else "")),
    (re.compile(r"(\d+(?:\.\d+)?)\s?%"), lambda m: f"{m.group(1)} percent"),
    (re.compile(r"\bDr\.\s*"), lambda m: "Doctor "),
    (re.compile(r"\bDLP\b"), lambda m: "defects liability period"),
]


def speakable(line: str) -> str:
    """What George reads for a line written for the screen (a kind's own words carry figures, not a `say`). The file
    is still named by the line itself, so the dashboard finds it."""
    for pattern, words in _SAY:
        line = pattern.sub(words, line)
    return line


def file_id(line: str) -> str:
    return hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]  # noqa: S324 (a file name, not security)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="record every line again")
    force = ap.parse_args().force
    lines: list[str] = json.loads(LINES.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    ids = {line: file_id(line) for line in lines}
    missing = []
    for line, fid in ids.items():
        path = OUT / f"{fid}.mp3"
        if force or not path.exists():
            print(f"voice {fid}: {line[:70]}")
            try:
                scene.tts(speakable(line), path)
            except urllib.error.HTTPError as err:  # e.g. the month's quota spent: the rest are recorded next run
                print(f"  not recorded ({err.code}): {err.read()[:160]!r}")
                missing.append(line)
    for stale in OUT.glob("*.mp3"):
        if stale.stem not in ids.values():
            print(f"remove {stale.name}")
            stale.unlink()
    # Only the lines that have a file: any other is read by the server's voice until it is recorded.
    ids = {line: fid for line, fid in ids.items() if (OUT / f"{fid}.mp3").exists()}
    body = "\n".join(f"  {json.dumps(line, ensure_ascii=False)}: '{fid}'," for line, fid in sorted(ids.items()))
    GEN.write_text(
        "// Made by scripts/scene_audio/make_guide_audio.py (UX-76): do not edit by hand.\n"
        "// Each walkthrough line recorded with ElevenLabs, and its file in public/learn/voice.\n"
        f"export const GUIDE_AUDIO: Record<string, string> = {{\n{body}\n}}\n",
        encoding="utf-8",
    )
    total = sum((OUT / f"{fid}.mp3").stat().st_size for fid in ids.values())
    print(f"{len(ids)} lines, {total / 1024:.0f} KB; wrote {GEN.relative_to(ROOT)}"
          + (f"; {len(missing)} not recorded yet: run again" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
