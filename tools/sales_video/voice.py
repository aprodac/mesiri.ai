"""Narration for the sales video: English line -> colloquial Malayalam (Sarvam mayura) -> speech (bulbul:v3).

    python tools/sales_video/voice.py OUT_DIR [--lang ml-IN|en-IN] [--estimate]

Writes, per line, ``OUT_DIR/audio/<scene>-<n>.wav`` and the text spoken (``OUT_DIR/spoken.json``, review it), and
``OUT_DIR/timing.json``: each scene's lines with their start and length in seconds, the scene's total. Everything is
cached: lines already voiced are not sent again. ``--estimate`` (or Sarvam refusing, e.g. no credits) writes silent
audio of an estimated length instead, so the visuals can be built and checked before the voice exists.

The key is never in this file: the request goes to api.sarvam.ai with a dummy key, which the environment's proxy
replaces (or set SARVAM_API_KEY when running elsewhere).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.sarvam.ai"
#: Silence before a scene's first line, between lines, and after the last one (seconds).
LEAD, GAP, TAIL = 0.6, 0.45, 0.9
#: Words a second when the length is estimated (Malayalam runs longer than the English).
WPS = {"ml-IN": 2.0, "en-IN": 2.6}


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "api-subscription-key": os.environ.get("SARVAM_API_KEY", "dummy")})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def translate(text: str, lang: str) -> str:
    if lang == "en-IN":
        return text
    out = _post("/translate", {"input": text, "source_language_code": "en-IN", "target_language_code": lang,
                               "model": "mayura:v1", "mode": "modern-colloquial", "speaker_gender": "Female"})
    return out["translated_text"]


def speak(text: str, lang: str, path: Path) -> None:
    out = _post("/text-to-speech", {"text": text, "target_language_code": lang, "speaker": "priya",
                                    "model": "bulbul:v3", "pace": 1.0, "speech_sample_rate": 24000})
    path.write_bytes(base64.b64decode(out["audios"][0]))


def silence(seconds: float, path: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t",
                    f"{seconds:.2f}", path], check=True)


def length(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--lang", default="ml-IN")
    ap.add_argument("--estimate", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    script = json.loads((HERE / "script.json").read_text())
    spoken_path = out / "spoken.json"
    spoken = json.loads(spoken_path.read_text()) if spoken_path.exists() else {}
    timing, estimated = [], False
    for scene in script["scenes"]:
        t, lines = LEAD, []
        for n, line in enumerate(scene["lines"]):
            key = f"{scene['id']}-{n}"
            wav = out / "audio" / f"{key}.wav"
            # A line corrected by hand (script.json "ml_overrides") is spoken as written, never machine-translated.
            fixed = script.get("ml_overrides", {}).get(key) if a.lang == "ml-IN" else None
            have = spoken.get(key, {})
            fresh = (not wav.exists() or have.get("en") != line or have.get("estimated")
                     or (fixed is not None and have.get("spoken") != fixed))
            if fresh:
                try:
                    if a.estimate:
                        raise RuntimeError("estimate asked")
                    said = fixed or translate(line, a.lang)
                    speak(said, a.lang, wav)
                    spoken[key] = {"en": line, "spoken": said, "lang": a.lang}
                except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, KeyError) as exc:
                    detail = exc.read().decode()[:200] if isinstance(exc, urllib.error.HTTPError) else str(exc)
                    if not a.estimate:
                        print(f"  {key}: Sarvam refused ({detail}); estimated length, silent", file=sys.stderr)
                    silence(len(line.split()) / WPS.get(a.lang, 2.2) + 0.3, wav)
                    spoken[key] = {"en": line, "spoken": None, "lang": a.lang, "estimated": True}
                    estimated = True
                spoken_path.write_text(json.dumps(spoken, ensure_ascii=False, indent=1))
            d = length(wav)
            lines.append({"key": key, "en": line, "start": round(t, 3), "dur": round(d, 3)})
            t += d + GAP
        timing.append({"id": scene["id"], "visual": scene["visual"], "part": scene.get("part"),
                       "value": scene.get("value"), "lines": lines, "total": round(t - GAP + TAIL, 3)})
    (out / "timing.json").write_text(json.dumps(timing, indent=1))
    total = sum(s["total"] for s in timing)
    print(f"{len(timing)} scenes, {total / 60:.1f} min{' (estimated: no voice yet)' if estimated else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
