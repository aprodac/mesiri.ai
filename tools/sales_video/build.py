"""Put the sales video together: each recorded scene cut to its narration, the voice, English subtitles.

    python tools/sales_video/build.py OUT_DIR [NAME]

Reads OUT_DIR/timing.json, OUT_DIR/audio/*.wav (voice.py) and OUT_DIR/scenes/*.webm + .json (record.js). Writes
OUT_DIR/NAME.mp4 (1920x1080, H.264 + AAC) and OUT_DIR/NAME.srt (the English subtitles, also burned in).
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

FPS = 30
RATE = 24000
FADE = 0.35


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def stamp(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> int:
    out = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else "mesiri-drawings-sales-training"
    timing = json.loads((out / "timing.json").read_text())
    work = out / "build"
    work.mkdir(exist_ok=True)
    parts, subs, offset = [], [], 0.0
    voice = bytearray()
    for scene in timing:
        meta = json.loads((out / "scenes" / f"{scene['id']}.json").read_text())
        total = scene["total"]
        clip = work / f"{scene['id']}.mp4"
        # The picture: from the moment the narration starts, as long as the narration, 1080p, faded in and out.
        run("-ss", f"{meta['cut']:.3f}", "-i", str(out / "scenes" / f"{scene['id']}.webm"), "-t", f"{total:.3f}",
            "-vf", f"scale=1920:1080:flags=lanczos,fps={FPS},tpad=stop_mode=clone:stop_duration={total:.3f},"
                   f"trim=duration={total:.3f},fade=t=in:st=0:d={FADE},fade=t=out:st={total - FADE:.3f}:d={FADE},"
                   "format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(clip))
        parts.append(clip)
        # The voice: each line at its start, silence between.
        track = bytearray(int(total * RATE) * 2)
        for line in scene["lines"]:
            with wave.open(str(out / "audio" / f"{line['key']}.wav")) as w:
                if w.getframerate() != RATE or w.getsampwidth() != 2 or w.getnchannels() != 1:
                    raise SystemExit(f"{line['key']}: expected {RATE} Hz 16-bit mono")
                data = w.readframes(w.getnframes())
            at = int(line["start"] * RATE) * 2
            track[at:at + len(data)] = data[: max(0, len(track) - at)]
            subs.append((offset + line["start"], offset + line["start"] + line["dur"], line["en"]))
        voice += track
        offset += total
    with wave.open(str(work / "voice.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(voice))
    srt = out / f"{name}.srt"
    srt.write_text("\n".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for i, (a, b, text) in enumerate(subs, 1)),
                   encoding="utf-8")
    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts))
    run("-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", str(work / "picture.mp4"))
    style = ("FontName=Inter,FontSize=15,PrimaryColour=&H00FFFFFF,BackColour=&HA0101828,BorderStyle=3,Outline=6,"
             "Shadow=0,MarginV=22,MarginL=60,MarginR=60,Alignment=2,Bold=1")
    run("-i", str(work / "picture.mp4"), "-i", str(work / "voice.wav"),
        "-vf", f"subtitles={srt}:force_style='{style}'", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-movflags", "+faststart",
        "-shortest", str(out / f"{name}.mp4"))
    print(f"{out / f'{name}.mp4'}: {offset / 60:.1f} min, {len(parts)} scenes, {len(subs)} subtitles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
