// UX-76: the walkthroughs' spoken lines, as the browser sends them (lib/voice.ts voiceWords of
// lib/walkthroughs.ts spokenWords), for make_guide_audio.py to record once with ElevenLabs.
//
//     node scripts/scene_audio/guide_lines.mjs     # writes scripts/scene_audio/guide-lines.json
//
// Reads the dashboard's own TypeScript through Vite, so the lines are exactly what plays: every step of every voiced
// walkthrough (VOICED). A line with no recording (a step changed since, a hint) is read by the server's voice.
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
  const lines = new Set()
  for (const id of w.VOICED) {
    const walk = w.findWalkthrough(id)
    if (!walk) throw new Error(`VOICED names ${id}, which is no walkthrough`)
    for (const step of walk.steps) lines.add(v.voiceWords(w.spokenWords(step), 'guide'))
  }
  const out = [...lines].sort()
  writeFileSync(join(here, 'guide-lines.json'), JSON.stringify(out, null, 1) + '\n')
  console.log(`${out.length} lines, ${out.reduce((n, l) => n + l.length, 0)} characters`)
} finally {
  await server.close()
}
