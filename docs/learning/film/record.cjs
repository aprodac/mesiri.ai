#!/usr/bin/env node
// LRN-F15: record an episode's real entries from a local copy of Mesiri, never production.
//
//   node docs/learning/film/record.cjs 03 <your own token> [http://localhost:5199] [http://localhost:8000]
//   ONLY=rain,office node docs/learning/film/record.cjs 03 <token>   # only these scenes (days still played from 0)
//
// Starts the person's sample company afresh (DELETE then POST /learn/sandbox), then goes day by day through the scenes
// that have a day, in the order of their days:
// - a scene of kind `steps` with `as` (a role) and `day` is filmed first on its day, by shoot.cjs (steps-NN.cjs does
//   the actions) inside the sample company as that role, before the episode's own messages of that day; then the copy
//   goes back to the start of the day (Go back), so the messages that follow find the day as it was.
// - a chat scene with `capture` is sent for real to the assistant (POST /assistant/messages, the same handler as a
//   WhatsApp message) as `capture.role`, on `capture.day`; the reply is written to .cache/shots/<scene>.chat.json, the
//   button named `capture.tap` is tapped and its answer kept too. build.mjs draws these in place of the script's guess.
// Needs the API with a model key (the assistant answers for real), the dashboard served (for `steps`), Playwright.
const { spawnSync } = require('child_process')
const { readFileSync, writeFileSync, mkdirSync, existsSync } = require('fs')
const { join } = require('path')

const [, , epArg = '03', token, base = 'http://localhost:5199', apiBase = 'http://localhost:8000'] = process.argv
const ep = epArg.padStart(2, '0')
if (!token) throw new Error('usage: record.cjs NN <your own token> [dashboard] [api]')
const script = JSON.parse(readFileSync(join(__dirname, `episode-${ep}.json`), 'utf8'))
const out = join(__dirname, '.cache', 'shots')
mkdirSync(out, { recursive: true })

async function call(tok, method, path, body) {
  const r = await fetch(apiBase + path, { method, headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  const text = await r.text()
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${text.slice(0, 300)}`)
  return text ? JSON.parse(text) : {}
}

const sample = { day: 0, tokens: {}, answers: {} }
/** A token for this role in the sample company as it stands (the same copy: opening never replays). */
async function as(role) {
  const r = await call(token, 'POST', '/learn/sandbox', { role })
  sample.tokens[role] = r.token
  sample.answers[role] = r
  return r.token
}
async function playTo(day, role) {
  while (day > sample.day) { // the API moves at most 7 days a call
    const r = await call(token, 'POST', '/learn/sandbox/next-day', { role, days: Math.min(7, day - sample.day) })
    if ((r.failed || []).length) console.warn(`  day ${r.day}: ${r.failed.length} entries failed`)
    sample.day = r.day
    sample.tokens[role] = r.token
    sample.answers[role] = r
  }
  return sample.tokens[role] || as(role)
}

/** One message to the assistant as the sample's person; the button named `tap` is pressed after. */
async function capture(sc) {
  const c = sc.capture
  const tok = await playTo(c.day, c.role)
  const sent = await call(tok, 'POST', '/assistant/messages', { text: c.send })
  const reply = sent.replies || []
  // Mesiri may ask first (which metal, which cash box): `capture.choose` names the answers to tap, in any order; then
  // the button named `capture.tap` (Save). Each tap and Mesiri's answer to it is kept, for the film to show.
  const turns = []
  let last = reply
  let press = null
  const title = (b) => b.title.replace(/^\W+/, '').trim().toLowerCase()
  for (let i = 0; i < 5 && c.tap; i++) {
    const buttons = last.flatMap((r) => r.buttons || [])
    const pick = buttons.find((b) => (c.choose || []).some((w) => title(b) === w.toLowerCase()) && !turns.some((t) => t.tapped === b.title))
    press = pick || buttons.find((b) => title(b) === c.tap.toLowerCase())
    if (!press) break
    last = (await call(tok, 'POST', '/assistant/messages', { interactive_reply_id: press.id })).replies || []
    turns.push({ tapped: press.title, reply: last })
    if (!pick) break
  }
  if (c.tap && !turns.some((t) => title({ title: t.tapped }) === c.tap.toLowerCase())) console.warn(`  ${sc.id}: "${c.tap}" was never pressed`)
  const after = turns.length ? turns[turns.length - 1].reply : []
  writeFileSync(join(out, `${sc.id}.chat.json`), JSON.stringify({ sent: c.send, as: c.role, day: c.day, reply, turns, after }, null, 1))
  console.log(`${sc.id}: ${reply.map((r) => r.text.split('\n')[0]).join(' / ')} → ${turns.map((t) => t.tapped).join(' → ') || '(no tap)'}`)
}

/** A website scene (kind steps), filmed by shoot.cjs with steps-NN.cjs, inside the sample company as `sc.as` on
 *  `sc.day`; then the day goes back to its start, so the episode's own messages of that day find it as it was. */
function steps(sc, mine) {
  return (async () => {
    await playTo(sc.day, mine)
    await as(sc.as)
    const file = join(out, `sample-${sc.id}.json`)
    writeFileSync(file, JSON.stringify(sample.answers[sc.as]))
    const r = spawnSync('node', [join(__dirname, 'shoot.cjs'), ep, token, base, apiBase],
      { env: { ...process.env, ONLY: sc.id, SAMPLE: file }, stdio: 'inherit' })
    if (r.status !== 0) throw new Error(`${sc.id}: shoot.cjs failed`)
    const back = await call(token, 'POST', '/learn/sandbox/go-back', { day: sc.day, role: mine })
    sample.tokens = { [mine]: back.token }
    sample.answers = { [mine]: back }
  })()
}

;(async () => {
  const only = process.env.ONLY ? process.env.ONLY.split(',') : null
  const chats = script.scenes.filter((s) => s.kind === 'chat' && s.capture && (!only || only.includes(s.id)))
  const webs = script.scenes.filter((s) => s.kind === 'steps' && s.as && (!only || only.includes(s.id)))
  const mine = chats[0]?.capture.role || 'OWNER'
  // A fresh sample company, on day 0: never record on a copy left from an earlier run (its days would be wrong).
  for (let i = 0; ; i++) {
    try {
      await call(token, 'DELETE', '/learn/sandbox')
      break
    } catch (e) {
      if (i === 2) throw new Error(`could not start the sample company afresh: ${e.message}`)
      await new Promise((r) => setTimeout(r, 5000))
    }
  }
  await as(mine)
  const clock = await call(token, 'GET', `/learn/sandbox/clock?role=${mine}`)
  if (clock.day !== 0) throw new Error(`the sample company opened on day ${clock.day}, not 0`)
  console.log(`sample company opened as ${mine}, day 0`)
  const days = [...new Set([...chats.map((s) => s.capture.day), ...webs.map((s) => s.day)])].sort((a, b) => a - b)
  for (const day of days) {
    for (const sc of webs.filter((s) => s.day === day)) await steps(sc, mine)
    for (const sc of chats.filter((s) => s.capture.day === day)) await capture(sc)
  }
  console.log(`done: the sample company is on day ${sample.day}`)
})().catch((e) => {
  console.error(e.message)
  process.exit(1)
})
