"""Build the Cost control sales video: Malayalam voice (Sarvam), dashboard frames (Playwright, the installed Chrome),
English subtitles drawn into each frame, assembled with ffmpeg. Same steps as ../accounts/build.py.

  SARVAM_API_KEY=... python3 build.py voice     speak every line (cached by text)
  python3 build.py frames                       cards, dashboard shots with highlights, one frame per line
  python3 build.py video                        mesiri-cost-control.mp4, .en.srt and the script (EN + ML)

Needs: the local API on :8000 and the dashboard on :5173 against the demo database (seed.py), ffmpeg, Google Chrome.
The subtitles are drawn into the frames (no libass needed), in a band under the picture so they never cover it.
"""
import base64
import hashlib
import html
import json
import os
import subprocess
import sys
import time
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, "..", "accounts"))  # after this folder: both have a script.py
import slides  # noqa: E402  (the Accounts video's look)
from script import GV, LINES, LV  # noqa: E402

OUT = os.path.join(HERE, "build")
os.makedirs(OUT, exist_ok=True)
SPEAKER, MODEL, RATE = "kavitha", "bulbul:v3", 24000  # the Accounts video's voice
GAP, LEAD, TAIL = 0.45, 1.6, 1.2  # seconds: between lines, the opening card, after the last line
NAME = "mesiri-cost-control"


def h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def lines():
    out, shot = [], None
    for i, ln in enumerate(LINES):
        shot = ln["shot"] if ln["shot"] is not None else shot
        out.append({**ln, "i": i, "shot": shot})
    return out


# -- voice -----------------------------------------------------------------------------------------------------------

def speak(text: str, path: str) -> None:
    body = json.dumps({"text": text, "target_language_code": "ml-IN", "model": MODEL, "speaker": SPEAKER, "pace": 1.0,
                       "speech_sample_rate": RATE}).encode()
    req = urllib.request.Request("https://api.sarvam.ai/text-to-speech", data=body, headers={
        "api-subscription-key": os.environ["SARVAM_API_KEY"], "content-type": "application/json"})
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=120))
            open(path, "wb").write(base64.b64decode("".join(d["audios"])))
            return
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"text-to-speech {e.code}: {e.read()[:300]!r}") from e


def wav_path(ln) -> str:
    return os.path.join(OUT, f"v_{h(ln['ml'] + SPEAKER + MODEL)}.wav")


def duration(path: str) -> float:
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def voice():
    for ln in lines():
        if not os.path.exists(wav_path(ln)):
            speak(ln["ml"], wav_path(ln))
            print("spoke", ln["i"], round(duration(wav_path(ln)), 1), "s")
    print("voice done:", round(sum(duration(wav_path(ln)) for ln in lines()), 1), "s of speech")


# -- frames ----------------------------------------------------------------------------------------------------------

LOGO = '<div class="logo">mesiri<span>.</span> Cost control</div>'
CARDS = {
    "hook": f"""<div class="wrap"><div class="kicker">Mesiri · Cost control</div>
      <h1>The money is spent.<br>Was the work done?</h1>
      <p class="lead">For a builder, the real question is not how much went out today. It is whether the work on site was
      worth it.</p></div>{LOGO}""",
    "problem": f"""<div class="wrap"><div class="kicker">One day on site</div><h2>The GM's question</h2>
      <div class="eq"><div class="box">4 masons<small>₹1,100 a day</small></div><div>+</div>
      <div class="box">2 helpers<small>₹1,000 a day</small></div><div>=</div><div class="box">₹6,400<small>wages today</small></div></div>
      <p class="big">Was ₹6,400 of work done?</p></div>{LOGO}""",
    "intro": f"""<div class="wrap"><div class="kicker">The answer</div><h1>Mesiri Cost control</h1>
      <p class="lead">For every BOQ item, every day: was the money spent matched by the work measured on site?</p>
      <div class="row"><div class="card"><h3><span class="dot emerald"></span>Green / red</h3><p>Each day and each BOQ line: labour
      against the work it earned.</p></div><div class="card"><h3><span class="dot amber"></span>Budget vs actual</h3><p>Budget,
      earned, spent and the forecast at completion.</p></div><div class="card"><h3><span class="dot rose"></span>Materials vs BOQ</h3>
      <p>Material used against what the work needed.</p></div></div></div>{LOGO}""",
    "whatsapp": f"""<div class="wrap"><div class="kicker">Every evening</div><h2>The cost card on WhatsApp</h2>
      <ul class="points"><li><i>1</i>Each site today: green, amber or red</li><li><i>2</i>The worst BOQ lines, with the reason</li>
      <li><i>3</i>Labour not yet on a BOQ line</li><li><i>4</i>Ask any time: "how is cost today?"</li></ul>
      <p class="lead">Sent to the owner, admins and the project manager of each project.</p></div>{LOGO}""",
    "roles": f"""<div class="wrap"><div class="kicker">Who sees what</div><h2>Money stays with the people who manage it</h2>
      <table><tr><th>Role</th><th>Sees</th></tr>
      <tr><td>Owner · Admin · Finance · Project manager</td><td>Everything: rates, budget, spent, forecast</td></tr>
      <tr><td>Site engineer</td><td>Their own site's green / red and quantities. <b class="bad">Never the money.</b></td></tr></table>
      </div>{LOGO}""",
    "close": """<div class="chapter"><div class="num">MESIRI · COST CONTROL</div>
      <h1>Know where costs run over,<br>before you pay.</h1>
      <p class="lead" style="color:#d4d4d8">Every rupee spent, matched to the work done.</p></div>""",
}

HIGHLIGHT_JS = r"""
([targets, sidebarX]) => {
  // Find each target as visible text (a text node, so a button's label next to its icon counts too), bring it to the
  // middle of the screen, and box it: the card it sits in when that card is not huge, else the text itself.
  const find = (t, sidebar) => {
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.nodeValue.includes(t)) continue
      const el = n.parentElement
      if (!el || !el.offsetParent || el.closest('select,option,[aria-hidden="true"]')) continue
      const r = el.getBoundingClientRect()
      if (!r.width || !r.height || sidebar !== (r.x < sidebarX)) continue
      return el
    }
    return null
  }
  const boxes = []
  for (const raw of targets) {
    const sidebar = raw.startsWith('sidebar:')
    const el = find(sidebar ? raw.slice(8) : raw, sidebar)
    if (!el) continue
    const r0 = el.getBoundingClientRect()
    if (!sidebar && (r0.top < 70 || r0.bottom > innerHeight - 30)) el.scrollIntoView({block: 'center'})
    let box = el.getBoundingClientRect()
    if (sidebar) {
      const group = el.closest('li'); if (group) box = group.getBoundingClientRect()
    } else {
      let p = el
      for (let i = 0; i < 6 && p; i++) {
        const cs = getComputedStyle(p), q = p.getBoundingClientRect()
        if ((cs.borderTopWidth !== '0px' || cs.borderLeftWidth !== '0px') && q.width < 1000 && q.height < 380 && q.width > 60) { box = q; break }
        p = p.parentElement
      }
    }
    const sec = (el.closest('section') || el).getBoundingClientRect()
    boxes.push({x: box.x, y: box.y, w: box.width, h: box.height, sec: {x: sec.x, y: sec.y, w: sec.width, h: sec.height}})
  }
  for (const b of boxes) {
    const d = document.createElement('div')
    Object.assign(d.style, {position: 'fixed', left: `${b.x - 6}px`, top: `${b.y - 6}px`, width: `${b.w + 12}px`,
      height: `${b.h + 12}px`, border: '4px solid #f59e0b', borderRadius: '12px', boxShadow: '0 0 0 6px rgba(245,158,11,.25)',
      zIndex: 99999, pointerEvents: 'none'})
    document.body.appendChild(d)
  }
  return boxes
}
"""


def shot_png(shot) -> str:
    return os.path.join(OUT, f"s_{h(json.dumps(shot, sort_keys=True))}.png")


def frame_png(ln) -> str:
    return os.path.join(OUT, f"f_{h(json.dumps(ln['shot'], sort_keys=True) + ln['en'])}.png")


def subtitle_page(picture: str, text: str) -> str:
    """1920x1080: the picture above, a dark band with the subtitle under it."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      *{{margin:0;padding:0;box-sizing:border-box}} body{{width:1920px;height:1080px;background:#18181b;font-family:Inter,system-ui,sans-serif}}
      .pic{{width:1920px;height:900px;display:flex;align-items:center;justify-content:center;background:#18181b}}
      .pic img{{width:1920px;height:900px;object-fit:contain}}
      .sub{{height:180px;display:flex;align-items:center;justify-content:center;padding:0 140px;text-align:center;
            color:#fff;font-size:40px;line-height:1.3;font-weight:500}}
      .sub span{{background:rgba(0,0,0,.0)}}</style></head>
      <body><div class="pic"><img src="data:image/png;base64,{base64.b64encode(open(picture, "rb").read()).decode()}"></div><div class="sub"><span>{html.escape(text)}</span></div></body></html>"""


def frames():
    from playwright.sync_api import sync_playwright

    tokens = {k: open(os.path.join(HERE, f"{k}.token")).read().strip() for k in ("admin", "engineer")}
    req = urllib.request.Request("http://localhost:8000/projects", headers={"Authorization": f"Bearer {tokens['admin']}"})
    listed = json.load(urllib.request.urlopen(req))
    ids = {p["name"]: p["id"] for p in (listed.get("items", []) if isinstance(listed, dict) else listed)}
    gv, lv = ids["Green Villa"], ids["Lake View Apartments"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        card = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
        contexts = {}
        for ln in lines():
            shot, out = ln["shot"], shot_png(ln["shot"])
            if os.path.exists(out):
                continue
            if isinstance(shot, str):
                card.set_content(slides.page(CARDS[shot.split(":", 1)[1]], dark=shot == "card:close"), wait_until="load")
                card.wait_for_timeout(200)
                card.screenshot(path=out)
                print("card", shot)
                continue
            who = shot.get("as", "admin")
            if who not in contexts:
                contexts[who] = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
                contexts[who].add_init_script(f"localStorage.setItem('mesiri_dashboard_token', {json.dumps(tokens[who])})")
            page = contexts[who].new_page()
            page.goto("http://localhost:5173" + shot["url"].replace(GV, gv).replace(LV, lv), wait_until="networkidle")
            page.wait_for_timeout(1800)
            if shot.get("scroll"):
                # To the element whose whole text is the scroll target (a section heading), near the top of the screen.
                page.evaluate("""(t) => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
                  for (let n = w.nextNode(); n; n = w.nextNode()) if (n.nodeValue.trim() === t && n.parentElement.offsetParent) {
                    n.parentElement.scrollIntoView({block: 'start'}); window.scrollBy(0, -110); return } }""", shot["scroll"])
                page.wait_for_timeout(400)
            boxes = page.evaluate(HIGHLIGHT_JS, [shot.get("hl", []), 300])
            if shot.get("hl") and not boxes:
                print("NO HIGHLIGHT", shot)
            if shot.get("zoom") and boxes:
                # A close-up of what is boxed: its card and some room around it, wide, so the picture fills the frame.
                b = boxes[0]["sec"]
                pad = 16
                x, y = max(b["x"] - pad, 0), max(b["y"] - pad, 0)
                w = min(b["w"] + 2 * pad, 1600 - x)
                hgt = min(b["h"] + 2 * pad, 900 - y)
                page.screenshot(path=out, clip={"x": x, "y": y, "width": w, "height": hgt})
            else:
                page.screenshot(path=out)
            print("page", shot["url"], "highlights", len(boxes))
            page.close()
        sub = browser.new_page(viewport={"width": 1920, "height": 1080})
        for ln in lines():
            out = frame_png(ln)
            if not os.path.exists(out):
                sub.set_content(subtitle_page(shot_png(ln["shot"]), ln["en"]), wait_until="load")
                sub.wait_for_timeout(100)
                sub.screenshot(path=out)
        browser.close()
    print("frames done")


# -- video -----------------------------------------------------------------------------------------------------------

def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def video():
    pcm, concat, subs = [], [], []
    md = ["# Mesiri Cost control: sales video script (Malayalam voice, English subtitles)\n\n"]
    first = lines()[0]
    concat.append(f"file '{shot_png(first['shot'])}'\nduration {LEAD:.3f}\n")
    pcm.append(silence(LEAD))
    t = LEAD
    for ln in lines():
        with wave.open(wav_path(ln)) as w:
            assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, wav_path(ln)
            data = w.readframes(w.getnframes())
        d = len(data) / 2 / RATE
        hold = d + (TAIL if ln is lines()[-1] else GAP)
        subs.append((t, t + d, ln["en"]))
        pcm.append(data + silence(hold - d))
        concat.append(f"file '{frame_png(ln)}'\nduration {hold:.3f}\n")
        t += hold
        md.append(f"{ln['i'] + 1}. **EN:** {ln['en']}\n   **ML:** {ln['ml']}\n\n")
    concat.append(f"file '{frame_png(lines()[-1])}'\n")
    open(os.path.join(OUT, "frames.txt"), "w").write("".join(concat))
    with wave.open(os.path.join(OUT, "voice.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(pcm))
    open(os.path.join(HERE, f"{NAME}.en.srt"), "w").write(
        "".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(subs, 1)))
    open(os.path.join(HERE, f"{NAME}-script.md"), "w").write("".join(md))
    out = os.path.join(HERE, f"{NAME}.mp4")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", os.path.join(OUT, "frames.txt"), "-i", os.path.join(OUT, "voice.wav"),
                    "-vf", "scale=1920:1080,fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
                    "-tune", "stillimage", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", out], check=True)
    print("video", out, f"{int(t // 60)}:{int(t % 60):02d}")


if __name__ == "__main__":
    {"voice": voice, "frames": frames, "video": video}[sys.argv[1]]()
