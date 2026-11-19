#!/usr/bin/env node
// FILM-01: build a Mesiri course film episode from its script (episode-NN.json) into an MP4 with narration and
// subtitles burned in.
//
//   node docs/learning/film/build.mjs 01            # build episode 1 (only what changed is made again)
//   ONLY=cement node docs/learning/film/build.mjs 01  # one scene's video, for a look (out/scene-cement.mp4)
//
// - Narration: ElevenLabs text to speech, voice "George" (the voice of the simulation's scenes, UX-73), one clip per
//   beat, kept in .cache by its words (a changed line is simply a new clip). Needs ELEVENLABS_API_KEY, or a Claude
//   Code session whose proxy fills it in.
// - Picture: film.html draws each scene at 1920×1080; Playwright seeks its animations frame by frame (24 fps) and
//   ffmpeg encodes them, so the picture is exactly in time with the beats.
// - Sound under it: the simulation's own whoosh between scenes and its credits music under the opening and the end
//   (apps/dashboard/public/learn/scenes).
// Output: docs/learning/film/out/episode-NN.mp4 and .srt (not committed: share the file).
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
let chromium
try {
  ;({ chromium } = require('playwright'))
} catch {
  ;({ chromium } = require(require.resolve('playwright', { paths: ['/usr/lib/node_modules', '/usr/local/lib/node_modules'] })))
}

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..', '..', '..')
const ep = (process.argv[2] || '01').padStart(2, '0')
const script = JSON.parse(readFileSync(join(here, `episode-${ep}.json`), 'utf8'))
const CACHE = join(here, '.cache')
const OUT = join(here, 'out')
const SOUNDS = join(root, 'apps', 'dashboard', 'public', 'learn', 'scenes')
mkdirSync(CACHE, { recursive: true })
mkdirSync(OUT, { recursive: true })

const VOICE = 'JBFqnCBsd6RMkjVDRZzb' // George: warm, captivating storyteller
const MODEL = 'eleven_multilingual_v2'
const FPS = 24
const LEAD = 900 // ms before the first beat of a scene
const GAP = 420 // ms between beats
const TAIL = 1500 // ms after the last beat
const hash = (s) => createHash('sha1').update(s).digest('hex').slice(0, 16)

function durationMs(file) {
  const r = spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file], { encoding: 'utf8' })
  return Math.round(parseFloat(r.stdout) * 1000)
}

function speak(text) {
  const file = join(CACHE, `say-${hash(`${VOICE}|${MODEL}|${text}`)}.mp3`)
  if (existsSync(file)) return file
  const body = JSON.stringify({ text, model_id: MODEL, voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0.3, use_speaker_boost: true } })
  const r = spawnSync('curl', ['-sS', '-f', '-o', file, `https://api.elevenlabs.io/v1/text-to-speech/${VOICE}?output_format=mp3_44100_128`,
    '-H', `xi-api-key: ${process.env.ELEVENLABS_API_KEY || 'set-by-proxy'}`, '-H', 'Content-Type: application/json', '--data-binary', body], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`text to speech failed for "${text.slice(0, 40)}…": ${r.stderr}`)
  return file
}

// 1. The narration and each scene's timing.
let clock = 0
const scenes = script.scenes.map((scene, index) => {
  let t = LEAD
  const beats = scene.beats.map((say) => {
    const file = speak(say)
    const len = durationMs(file)
    const b = { at: t, len, say, file }
    t += len + GAP
    return b
  })
  const dur = t - GAP + TAIL
  const s = { scene, index, beats, dur, start: clock }
  clock += dur
  console.log(`${scene.id.padEnd(10)} ${(dur / 1000).toFixed(1)} s, ${beats.length} beats`)
  return s
})
const total = clock
console.log(`episode ${ep}: ${(total / 60000).toFixed(1)} min`)

// 2. The picture, one scene at a time (kept while the scene, its timing and film.html are unchanged).
const page = readFileSync(join(here, 'film.html'), 'utf8')
async function render(browser, s, file) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  const pg = await ctx.newPage()
  const data = { scene: s.scene, beats: s.beats.map(({ at, len, say }) => ({ at, len, say })), dur: s.dur, index: s.index, total: scenes.length, episode: script.episode, title: script.title }
  await pg.addInitScript((d) => { window.SCENE = d }, data)
  await pg.goto(pathToFileURL(join(here, 'film.html')).href)
  await pg.evaluate(() => window.ready)
  await pg.waitForTimeout(300)
  const enc = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', String(FPS), file], { stdio: ['pipe', 'inherit', 'inherit'] })
  const frames = Math.ceil((s.dur / 1000) * FPS)
  for (let f = 0; f < frames; f++) {
    await pg.evaluate((t) => window.seek(t), (f * 1000) / FPS)
    const shot = await pg.screenshot({ type: 'jpeg', quality: 88 })
    if (!enc.stdin.write(shot)) await new Promise((r) => enc.stdin.once('drain', r))
  }
  enc.stdin.end()
  await new Promise((r, j) => enc.on('close', (c) => (c === 0 ? r() : j(new Error(`ffmpeg ${c}`)))))
  await ctx.close()
}

const browser = await chromium.launch()
// STILLS=1: each scene's last moment as a picture (out/stills), to check the layout without drawing the film.
if (process.env.STILLS) {
  mkdirSync(join(OUT, 'stills'), { recursive: true })
  for (const s of scenes) {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
    const pg = await ctx.newPage()
    const data = { scene: s.scene, beats: s.beats.map(({ at, len, say }) => ({ at, len, say })), dur: s.dur, index: s.index, total: scenes.length, episode: script.episode, title: script.title }
    await pg.addInitScript((d) => { window.SCENE = d }, data)
    await pg.goto(pathToFileURL(join(here, 'film.html')).href)
    await pg.evaluate(() => window.ready)
    await pg.evaluate((t) => window.seek(t), s.dur - 800)
    await pg.screenshot({ path: join(OUT, 'stills', `${String(s.index + 1).padStart(2, '0')}-${s.scene.id}.jpg`), type: 'jpeg', quality: 80 })
    await ctx.close()
  }
  await browser.close()
  console.log(`stills in ${join(OUT, 'stills')}`)
  process.exit(0)
}
const parts = []
for (const s of scenes) {
  if (process.env.ONLY && process.env.ONLY !== s.scene.id) continue
  const key = hash(JSON.stringify([s.scene, s.beats.map((b) => [b.at, b.len]), s.dur, s.index, scenes.length, page]))
  const file = join(CACHE, `scene-${s.scene.id}-${key}.mp4`)
  if (!existsSync(file)) {
    const t0 = Date.now()
    await render(browser, s, file)
    console.log(`  drew ${s.scene.id} in ${((Date.now() - t0) / 1000).toFixed(0)} s`)
  }
  parts.push({ s, file })
}
await browser.close()

const run = (args) => {
  const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(r.stderr)
}

// 3. The sound: every beat at its place, a whoosh as each scene opens, music under the first and last scenes.
function mixAudio(list, offset, out) {
  const inputs = []
  const chains = []
  const add = (file, at, vol) => {
    const i = inputs.length / 2
    inputs.push('-i', file)
    chains.push(`[${i}]adelay=${Math.max(0, Math.round(at))}|${Math.max(0, Math.round(at))},volume=${vol}[a${i}]`)
  }
  for (const { s } of list) {
    const base = s.start - offset
    if (s.index > 0) add(join(SOUNDS, 'sfx-whoosh.mp3'), base, 0.35)
    if (s.index === 0 || s.index === scenes.length - 1) add(join(SOUNDS, 'music-credits.mp3'), base, 0.16)
    for (const b of s.beats) add(b.file, base + b.at, 1)
  }
  const n = inputs.length / 2
  const graph = `${chains.join(';')};${Array.from({ length: n }, (_, i) => `[a${i}]`).join('')}amix=inputs=${n}:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]`
  run([...inputs, '-filter_complex', graph, '-map', '[out]', '-ac', '2', '-ar', '44100', '-c:a', 'aac', '-b:a', '160k', out])
}

const name = process.env.ONLY ? `scene-${process.env.ONLY}` : `episode-${ep}`
const offset = parts[0]?.s.start ?? 0
const list = join(CACHE, `${name}.txt`)
writeFileSync(list, parts.map((p) => `file '${p.file}'`).join('\n'))
const video = join(CACHE, `${name}-video.mp4`)
run(['-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', video])
const audio = join(CACHE, `${name}-audio.m4a`)
mixAudio(parts, offset, audio)
const out = join(OUT, `${name}.mp4`)
run(['-i', video, '-i', audio, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])

// Subtitles as a file too (for players that show them, or to translate later).
const ts = (ms) => {
  const h = String(Math.floor(ms / 3600000)).padStart(2, '0')
  const m = String(Math.floor(ms / 60000) % 60).padStart(2, '0')
  const sec = String(Math.floor(ms / 1000) % 60).padStart(2, '0')
  return `${h}:${m}:${sec},${String(Math.floor(ms % 1000)).padStart(3, '0')}`
}
let n = 0
const srt = parts.flatMap(({ s }) => s.beats.map((b) => `${++n}\n${ts(s.start - offset + b.at)} --> ${ts(s.start - offset + b.at + b.len + 200)}\n${b.say}\n`)).join('\n')
writeFileSync(join(OUT, `${name}.srt`), srt)
console.log(`wrote ${out} (${(durationMs(out) / 60000).toFixed(1)} min)`)
