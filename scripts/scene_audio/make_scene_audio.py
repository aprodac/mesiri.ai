#!/usr/bin/env python3
"""UX-73: the sound of the sample company's scenes (asked 19 Nov 2026: "go with A, warm English voice").

Makes the files once, into the dashboard's static files, so the VPS needs no voice key:

    python3 scripts/scene_audio/make_scene_audio.py            # only what is missing
    python3 scripts/scene_audio/make_scene_audio.py --force    # everything again

- The narrator's lines: ElevenLabs text to speech, voice "George" (warm storyteller), with ELEVENLABS_API_KEY
  (a Claude Code session's proxy fills it in). A changed line needs --force, or delete its file.
- The sound under them (whoosh, title boom, night, dawn, rewind, fast forward, the credits' music): made here with
  ffmpeg, no service (the key has no sound-effects or music permission).

Writes apps/dashboard/public/learn/scenes/<id>.mp3 and apps/dashboard/src/lib/scene-audio.gen.ts (each id and its
length in ms, which the scenes time themselves by). Played by apps/dashboard/src/lib/scene-sound.ts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "apps/dashboard/public/learn/scenes"
GEN = ROOT / "apps/dashboard/src/lib/scene-audio.gen.ts"
WALKS = ROOT / "apps/dashboard/src/lib/walkthroughs.ts"

VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George: warm, captivating storyteller (British, middle-aged)
MODEL = "eleven_multilingual_v2"
FORMAT = "mp3_44100_64"

NUMBERS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]

# The narrator's lines. The opening's cast names each role's own part last ("And you, ...").
LINES: dict[str, str] = {
    "open-title": "Green Villa Builders. Two projects on site, and Green Villa's last two months, to the handover.",
    "open-cast-ADMIN": "Meet the team. Anil, the project manager. Ravi, on site. Meera, in accounts. And you, the owner.",
    "open-cast-PROJECT_MANAGER": "Meet the team. The owner. Ravi, on site. Meera, in accounts. And you, Anil, the project manager.",
    "open-cast-SITE_ENGINEER": "Meet the team. The owner. Anil, the project manager. Meera, in accounts. And you, Ravi, on site.",
    "open-cast-FINANCE": "Meet the team. The owner. Anil, the project manager. Ravi, on site. And you, Meera, in accounts.",
    "open-day": "Two weeks on Mesiri so far. Let's begin.",
    "open-back": "Welcome back on site.",
    "pass-dusk": "The sun goes down on site. The team works through the day.",
    "pass-dawn": "Good morning.",
    "pass-skip": "Skipping ahead.",
    "pass-back": "Going back.",
    "briefing": "Here's what everyone did, and your part today.",
    "credits": "Green Villa, handed over. Kept by Mesiri, day by day.",
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def chapters() -> list[str]:
    """The guided project's chapter titles, read from JOURNEY_CHAPTERS, so a renamed chapter gets its line."""
    src = WALKS.read_text(encoding="utf-8")
    block = src[src.index("export const JOURNEY_CHAPTERS"):]
    block = block[: block.index("\n]\n")]
    return re.findall(r"\{ title: '([^']+)', walks:", block)


def chapter_lines() -> dict[str, str]:
    return {f"chapter-{slug(t)}": f"Chapter {NUMBERS[i]}. {t.rstrip('?')}{'?' if t.endswith('?') else '.'}" for i, t in enumerate(chapters())}


def tts(text: str, path: Path) -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "set-by-proxy")
    body = json.dumps({
        "text": text,
        "model_id": MODEL,
        "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.25, "use_speaker_boost": True},
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format={FORMAT}",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        path.write_bytes(res.read())


def chord(freqs: list[float], dur: float, amp: float) -> str:
    """A soft pad: the notes, each with a slow shimmer, faded in and out."""
    each = amp / len(freqs)
    voices = "+".join(f"{each:.3f}*sin(2*PI*{f}*t)*(0.8+0.2*sin(2*PI*0.3*t+{i}))" for i, f in enumerate(freqs))
    return f"aevalsrc='{voices}':d={dur}:s=44100"


# The sound under the lines: ffmpeg filter graphs (lavfi), each faded so it never clicks.
SFX: dict[str, list[str]] = {
    "sfx-whoosh": ["-f", "lavfi", "-i", "anoisesrc=d=1.3:c=pink:a=0.6",
                   "-af", "highpass=f=250,lowpass=f=2800,afade=t=in:d=0.55,afade=t=out:st=0.6:d=0.7,volume=0.9"],
    "sfx-boom": ["-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*(52+20*exp(-3*t))*t)*exp(-1.6*t)':d=3:s=44100",
                 "-af", "lowpass=f=180,afade=t=in:d=0.02,afade=t=out:st=2.2:d=0.8"],
    "sfx-night": ["-f", "lavfi", "-i", "anoisesrc=d=9:c=brown:a=0.35",
                  "-f", "lavfi", "-i", "aevalsrc='0.035*sin(2*PI*4400*t)*(gt(sin(2*PI*1.1*t),0.6))*(0.5+0.5*sin(2*PI*28*t))':d=9:s=44100",
                  "-filter_complex", "[0]lowpass=f=420[a];[a][1]amix=inputs=2:normalize=0,afade=t=in:d=1.2,afade=t=out:st=7.5:d=1.5"],
    "sfx-dawn": ["-f", "lavfi", "-i", chord([220.0, 277.18, 329.63, 440.0], 6, 0.5),
                 "-af", "lowpass=f=2200,afade=t=in:d=1.8,afade=t=out:st=3.8:d=2.2"],
    "sfx-rewind": ["-f", "lavfi", "-i", "aevalsrc='0.25*sin(2*PI*t*(1900-650*t))*(0.6+0.4*sin(2*PI*16*t))':d=2:s=44100",
                   "-af", "lowpass=f=3000,afade=t=in:d=0.1,afade=t=out:st=1.4:d=0.6"],
    "sfx-forward": ["-f", "lavfi", "-i", "aevalsrc='0.22*sin(2*PI*t*(500+650*t))*(0.6+0.4*sin(2*PI*20*t))':d=2:s=44100",
                    "-af", "lowpass=f=3200,afade=t=in:d=0.2,afade=t=out:st=1.4:d=0.6"],
}

# The credits' music: four warm chords (C, A minor, F, G), 6.5 s each, crossfaded: 26 s, the credits' roll.
MUSIC_CHORDS = [[261.63, 329.63, 392.0, 523.25], [220.0, 261.63, 329.63, 440.0], [174.61, 220.0, 261.63, 349.23], [196.0, 246.94, 293.66, 392.0]]


def ffmpeg(args: list[str], path: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-ac", "1", "-ar", "44100", "-b:a", "64k", str(path)], check=True)


def music(path: Path) -> None:
    inputs: list[str] = []
    for c in MUSIC_CHORDS:
        inputs += ["-f", "lavfi", "-i", chord(c, 8, 0.45)]
    graph = "[0][1]acrossfade=d=1.5[a];[a][2]acrossfade=d=1.5[b];[b][3]acrossfade=d=1.5,lowpass=f=1800,afade=t=in:d=2,afade=t=out:st=24:d=4"
    ffmpeg([*inputs, "-filter_complex", graph], path)


def duration_ms(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return round(float(out) * 1000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="make every file again")
    force = ap.parse_args().force
    OUT.mkdir(parents=True, exist_ok=True)
    lines = {**LINES, **chapter_lines()}
    for sid, text in lines.items():
        path = OUT / f"{sid}.mp3"
        if force or not path.exists():
            print(f"voice  {sid}: {text}")
            tts(text, path)
    for sid, args in SFX.items():
        path = OUT / f"{sid}.mp3"
        if force or not path.exists():
            print(f"sound  {sid}")
            ffmpeg(args, path)
    path = OUT / "music-credits.mp3"
    if force or not path.exists():
        print("music  music-credits")
        music(path)
    wanted = {*lines, *SFX, "music-credits"}
    for stale in OUT.glob("*.mp3"):
        if stale.stem not in wanted:
            print(f"remove {stale.name}")
            stale.unlink()
    lengths = {sid: duration_ms(OUT / f"{sid}.mp3") for sid in sorted(wanted)}
    body = "\n".join(f"  '{sid}': {ms}," for sid, ms in lengths.items())
    GEN.write_text(
        "// Made by scripts/scene_audio/make_scene_audio.py (UX-73): do not edit by hand.\n"
        "// Each scene sound in public/learn/scenes and its length in ms.\n"
        f"export const SCENE_AUDIO = {{\n{body}\n}} as const\n\n"
        "export type SceneAudioId = keyof typeof SCENE_AUDIO\n",
        encoding="utf-8",
    )
    total = sum((OUT / f"{sid}.mp3").stat().st_size for sid in wanted)
    print(f"{len(wanted)} files, {total / 1024:.0f} KB; wrote {GEN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
