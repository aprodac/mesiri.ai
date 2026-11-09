"""Build the training video: translate (Sarvam, code-mixed Malayalam), speak (Sarvam bulbul:v3), render frames,
time the English subtitles to each spoken line, and assemble with ffmpeg.

  python3 build.py voice     translate + speak every line (cached)
  python3 build.py frames    write slides and jobs, render frames with Playwright
  python3 build.py video     assemble mesiri-accounts-training.mp4 (+ .srt, + the Malayalam script)
"""
import hashlib, json, os, subprocess, sys, wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sarvam  # noqa: E402
import slides  # noqa: E402
from script import SCENES  # noqa: E402

OUT = os.path.join(HERE, "build")
os.makedirs(OUT, exist_ok=True)
GAP, SCENE_GAP, CARD = 0.35, 0.6, 2.4  # seconds: between lines, after a scene, the chapter card
RATE = 24000
SPEAKER = "kavitha"


def h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def lines():
    """Every line with its scene, subtitle, what is said, and the shot on screen."""
    out, shot = [], None
    for si, (title, ls) in enumerate(SCENES):
        for li, line in enumerate(ls):
            sub, s = line[0], line[1]
            say = line[2] if len(line) > 2 else sub
            if s is not None:
                shot = s
            out.append({"scene": si, "title": title, "i": li, "sub": sub, "say": say, "shot": shot})
    return out


def voice():
    cache_path = os.path.join(OUT, "ml.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for ln in lines():
        key = h(ln["say"])
        if key not in cache:
            cache[key] = sarvam.translate(ln["say"])
            json.dump(cache, open(cache_path, "w"), ensure_ascii=False, indent=1)
        wav = os.path.join(OUT, f"v_{h(cache[key] + SPEAKER)}.wav")
        if not os.path.exists(wav):
            sarvam.speak(cache[key], wav, SPEAKER)
            print("spoke", ln["scene"], ln["i"], round(duration(wav), 1), "s")
    print("voice done")


def duration(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def shot_key(shot) -> str:
    return h(json.dumps(shot, sort_keys=True))


def frames():
    tokens = {"finance": open(os.path.join(HERE, "finance.token")).read().strip(),
              "admin": open(os.path.join(HERE, "admin.token")).read().strip()}
    json.dump(tokens, open(os.path.join(OUT, "tokens.json"), "w"))
    # The supplier ledger shown in the Ledgers chapter.
    import urllib.request
    req = urllib.request.Request("http://localhost:8000/accounts/chart", headers={"Authorization": f"Bearer {tokens['finance']}"})
    chart = json.load(urllib.request.urlopen(req))
    malabar = next(x["id"] for x in chart["ledgers"] if x["name"] == "Malabar Steel Traders")
    jobs, seen = [], set()
    for si, (title, _) in enumerate(SCENES):
        path = os.path.join(OUT, f"card_{si:02d}.html")
        open(path, "w").write(slides.chapter(si + 1, title) if si else slides.page(slides.SLIDES["title"]))
        jobs.append({"kind": "html", "html": path, "out": os.path.join(OUT, f"card_{si:02d}.png"), "force": True})
    for ln in lines():
        shot = ln["shot"]
        k = shot_key(shot)
        if k in seen:
            continue
        seen.add(k)
        out = os.path.join(OUT, f"f_{k}.png")
        if isinstance(shot, str):
            name = shot.split(":", 1)[1]
            path = os.path.join(OUT, f"s_{name}.html")
            open(path, "w").write(slides.page(slides.SLIDES[name]))
            jobs.append({"kind": "html", "html": path, "out": out, "force": True})
        else:
            jobs.append({"kind": "url", **{**shot, "url": shot["url"].replace("__malabar__", f"/accounts/ledgers/{malabar}?range=fy")},
                         "out": out, "force": True})
    json.dump(jobs, open(os.path.join(OUT, "jobs.json"), "w"), indent=1)
    subprocess.run(["node", os.path.join(HERE, "render.js"), os.path.join(OUT, "jobs.json"), os.path.join(OUT, "tokens.json")],
                   check=True, cwd="/home/user/mesiri.ai")


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def video():
    cache = json.load(open(os.path.join(OUT, "ml.json")))
    pcm, concat, subs, script_md = [], [], [], ["# Mesiri Accounts: training script (Malayalam voice, English subtitles)\n"]
    t = 0.0
    last_scene = None

    def add_image(img: str, seconds: float):
        concat.append(f"file '{img}'\nduration {seconds:.3f}\n")

    for ln in lines():
        if ln["scene"] != last_scene:
            if last_scene is not None:
                pcm.append(silence(SCENE_GAP))
                add_image(concat_last[0], SCENE_GAP)
                t += SCENE_GAP
            card = os.path.join(OUT, f"card_{ln['scene']:02d}.png")
            pcm.append(silence(CARD))
            add_image(card, CARD)
            t += CARD
            last_scene = ln["scene"]
            script_md.append(f"\n## {ln['scene'] + 1}. {ln['title']}\n")
        ml = cache[h(ln["say"])]
        wav = os.path.join(OUT, f"v_{h(ml + SPEAKER)}.wav")
        with wave.open(wav) as w:
            assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, wav
            data = w.readframes(w.getnframes())
        d = len(data) / 2 / RATE
        img = os.path.join(OUT, f"f_{shot_key(ln['shot'])}.png")
        concat_last = [img]
        subs.append((t, t + d, ln["sub"]))
        pcm.append(data + silence(GAP))
        add_image(img, d + GAP)
        t += d + GAP
        script_md.append(f"- **EN:** {ln['sub']}\n  **ML:** {ml}\n")
    # The concat demuxer needs the last file repeated.
    concat.append(f"file '{concat_last[0]}'\n")
    open(os.path.join(OUT, "frames.txt"), "w").write("".join(concat))
    with wave.open(os.path.join(OUT, "voice.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(b"".join(pcm))
    srt = "".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(subs, 1))
    open(os.path.join(HERE, "mesiri-accounts-training.en.srt"), "w").write(srt)
    open(os.path.join(HERE, "mesiri-accounts-training-script.md"), "w").write("".join(script_md))
    # The picture sits above a dark band; the subtitles live in the band, so they never cover the screen.
    style = ("FontName=Inter,FontSize=9.5,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
             "Outline=0.6,Shadow=0,MarginV=6,MarginL=30,MarginR=30,Alignment=2,Bold=0")
    out = os.path.join(HERE, "mesiri-accounts-training.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(OUT, "frames.txt"),
        "-i", os.path.join(OUT, "voice.wav"),
        "-vf", f"scale=1707:960,pad=1920:1080:(ow-iw)/2:0:color=0x18181b,fps=25,"
               f"format=yuv420p,subtitles={os.path.join(HERE, 'mesiri-accounts-training.en.srt')}:force_style='{style}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-tune", "stillimage", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-shortest", out], check=True)
    print("video", out, round(t / 60, 1), "min")


if __name__ == "__main__":
    {"voice": voice, "frames": frames, "video": video}[sys.argv[1]]()
