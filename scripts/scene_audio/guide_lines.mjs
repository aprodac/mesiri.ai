// UX-76: the walkthroughs' spoken lines, as the browser sends them (lib/voice.ts voiceWords of
// lib/walkthroughs.ts spokenWords), for make_guide_audio.py to record once with ElevenLabs.
//
//     node scripts/scene_audio/guide_lines.mjs     # writes scripts/scene_audio/guide-lines.json
//
// Reads the dashboard's own TypeScript through Vite, so the lines are exactly what plays: every step of every voiced
// walkthrough (VOICED), for each kind of person, and every glossary word's hint. A line with no recording (a step
// changed since, a page's own hint) is read by the server's voice.
import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const dashboard = join(here, '..', '..', 'apps', 'dashboard')
const require = createRequire(join(dashboard, 'package.json'))
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)

const server = await createServer({ root: dashboard, server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })
try {
  const w = await server.ssrLoadModule('/src/lib/walkthroughs.ts')
  const v = await server.ssrLoadModule('/src/lib/voice.ts')
  const t = await server.ssrLoadModule('/src/lib/tours.ts')
  const g = await server.ssrLoadModule('/src/lib/glossary.ts')
  const lines = new Set()
  // Every step as each kind of person hears it (21 Nov: "the voice is so Indian"): a person who picked "new to
  // construction" or "new to tools" gets a step's own words for them (tours.ts stepFor, UX-22), which the plain words
  // alone never recorded, so they fell back to the server's voice.
  const kinds = [null, 'basics', 'steps', 'data', 'expert']
  for (const id of w.VOICED) {
    const walk = w.findWalkthrough(id)
    if (!walk) throw new Error(`VOICED names ${id}, which is no walkthrough`)
    for (const step of walk.steps) {
      for (const kind of kinds) {
        const mine = t.stepFor(step, kind)
        if (mine) lines.add(v.voiceWords(w.spokenWords(mine), 'guide'))
      }
    }
  }
  // A glossary word's "?" (components/hint.tsx): its heading, meaning and example, read by Listen.
  for (const term of g.GLOSSARY) {
    const word = term.match[0]
    const words = [word.charAt(0).toUpperCase() + word.slice(1), term.meaning, term.example].filter(Boolean).join('. ')
    lines.add(v.voiceWords(words, 'guide'))
  }
  const out = [...lines].sort()
  writeFileSync(join(here, 'guide-lines.json'), JSON.stringify(out, null, 1) + '\n')
  console.log(`${out.length} lines, ${out.reduce((n, l) => n + l.length, 0)} characters`)
} finally {
  await server.close()
}
