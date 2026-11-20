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


def file_id(line: str) -> str:
    return hashlib.sha1(line.encode("utf-8")).hexdigest()[:12]  # noqa: S324 (a file name, not security)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="record every line again")
    force = ap.parse_args().force
    lines: list[str] = json.loads(LINES.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    ids = {line: file_id(line) for line in lines}
    for line, fid in ids.items():
        path = OUT / f"{fid}.mp3"
        if force or not path.exists():
            print(f"voice {fid}: {line[:70]}")
            scene.tts(line, path)
    for stale in OUT.glob("*.mp3"):
        if stale.stem not in ids.values():
            print(f"remove {stale.name}")
            stale.unlink()
    body = "\n".join(f"  {json.dumps(line, ensure_ascii=False)}: '{fid}'," for line, fid in sorted(ids.items()))
    GEN.write_text(
        "// Made by scripts/scene_audio/make_guide_audio.py (UX-76): do not edit by hand.\n"
        "// Each walkthrough line recorded with ElevenLabs, and its file in public/learn/voice.\n"
        f"export const GUIDE_AUDIO: Record<string, string> = {{\n{body}\n}}\n",
        encoding="utf-8",
    )
    total = sum((OUT / f"{fid}.mp3").stat().st_size for fid in ids.values())
    print(f"{len(ids)} lines, {total / 1024:.0f} KB; wrote {GEN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
