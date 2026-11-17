import fs from 'node:fs'
import path from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const SRC = path.resolve(__dirname, './src')

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return sources(full)
    return /\.tsx?$/.test(entry.name) ? [full] : []
  })
}

/**
 * The guided tours (src/lib/tours.ts) point at elements by a marker on the element (`data-guide="today.send"`, or
 * `guide="..."` on the shared components that pass it on). A step whose marker is on no element any more would be
 * skipped without a word, so the build fails instead: whoever removes or renames a marked element fixes its tour
 * step in the same change.
 */
function checkTourMarkers(): Plugin {
  return {
    name: 'mesiri-check-tour-markers',
    buildStart() {
      // The page tours, the walkthroughs (SS-42, src/lib/walkthroughs.ts) and the help's parts (UX-22, `find:` in
      // src/lib/page-help.ts) point at markers the same way.
      const files = ['lib/tours.ts', 'lib/walkthroughs.ts', 'lib/page-help.ts']
      const guides = files.map((f) => fs.readFileSync(path.join(SRC, f), 'utf8')).join('\n')
      const wanted = [
        ...[...guides.matchAll(/(?:target|find): '([A-Za-z0-9._-]+)'/g)].map((m) => m[1]),
        // A tour's startWhen markers (the page's content it waits for) must exist too.
        ...[...guides.matchAll(/startWhen: \[([^\]]*)\]/g)].flatMap((m) => [...m[1].matchAll(/'([A-Za-z0-9._-]+)'/g)].map((x) => x[1])),
      ]
      const code = sources(SRC)
        .filter((file) => !files.some((f) => file.endsWith(path.join(...f.split('/')))))
        .map((file) => fs.readFileSync(file, 'utf8'))
        .join('\n')
      // A marker as text (data-guide="x", guide="x"), set by a condition (data-guide={next ? 'x' : undefined}), or on
      // one figure of a KPI strip (UX-15: { label: ..., guide: 'x' }).
      const has = (id: string) =>
        code.includes(`data-guide="${id}"`) || code.includes(`guide="${id}"`) || code.includes(`guide: '${id}'`) ||
        new RegExp(`guide=\\{[^}]*'${id.replace(/\./g, '\\.')}'`).test(code)
      const missing = wanted.filter((id) => !has(id))
      if (missing.length) {
        this.error(`Tour steps point at markers no element has (src/lib/tours.ts, src/lib/walkthroughs.ts): ${[...new Set(missing)].join(', ')}`)
      }
      // A walkthrough step's `page` must be a built page (module-map.ts), or the walkthrough would lead nowhere.
      const map = fs.readFileSync(path.join(SRC, 'lib/module-map.ts'), 'utf8')
      const built = new Set([...map.matchAll(/url: '([^']+)', status: 'built'/g)].map((m) => m[1]))
      const pages = [...guides.matchAll(/page: '([^']+)'/g)].map((m) => m[1])
      const gone = pages.filter((url) => !built.has(url) && !built.has(url.split('?')[0]))
      if (gone.length) {
        this.error(`Walkthrough steps go to pages that are not built pages in lib/module-map.ts: ${[...new Set(gone)].join(', ')}`)
      }
      // A workflow, outcome or role path made of other walkthroughs names them by id: each must exist. Ids are written
      // (`id: '...'`), or made from a page tour (`page-<path>`), a module (`module-<key>`), or an outcome (`goal-<id>`).
      const walks = fs.readFileSync(path.join(SRC, 'lib/walkthroughs.ts'), 'utf8')
      const tourKeys = [...guides.matchAll(/^ {2}'(\/[^']+)': \{/gm)].map((m) => `page${m[1].replace(/\//g, '-')}`)
      const moduleKeys = [...map.matchAll(/^ {4}key: '([a-z_-]+)'/gm)].map((m) => `module-${m[1]}`)
      const written = [...walks.matchAll(/\bid: '([a-z0-9-]+)'|(?:composed|journey)\(\s*'([a-z0-9-]+)'/g)].map((m) => m[1] ?? m[2])
      const known = new Set([...written, ...written.map((id) => `goal-${id}`), ...tourKeys, ...moduleKeys, 'app'])
      const lists = [...walks.matchAll(/walks: \[([^\]]*)\]/g), ...walks.matchAll(/composed\([^\n]*?\[([^\]]*)\]/g)]
      // SS-61: the walkthroughs given a voice (VOICED) must exist too.
      const voiced = [...walks.matchAll(/VOICED[^=]*= new Set\(\[([^\]]*)\]/g)]
      const unknown = [...lists, ...voiced].flatMap((m) => [...m[1].matchAll(/'([a-z0-9-]+)'/g)].map((x) => x[1])).filter((id) => !known.has(id))
      if (unknown.length) {
        this.error(`Walkthroughs made of walkthroughs that don't exist (src/lib/walkthroughs.ts): ${[...new Set(unknown)].join(', ')}`)
      }
    },
  }
}

// SCP-07: every built page of the module map has its row in lib/scope-levels.ts (how far it narrows to the project
// or site picked). The page's console error only shows in the screenshot run, and four pages slipped past it, so
// the build checks it too.
/**
 * SS-74a: one "now" (src/lib/clock.ts `appNow()`), so a learning sample company's own date reaches every page. A bare
 * `new Date()` would show the real date inside the game (a wrong "today", "days late", date field default), so the
 * build fails on one anywhere else.
 */
function checkOneClock(): Plugin {
  return {
    name: 'mesiri-check-one-clock',
    buildStart() {
      const found: string[] = []
      const walk = (dir: string) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          const full = path.join(dir, entry.name)
          if (entry.isDirectory()) walk(full)
          else if (/\.tsx?$/.test(entry.name) && !full.endsWith(path.join('lib', 'clock.ts'))) {
            fs.readFileSync(full, 'utf8').split('\n').forEach((line, i) => {
              if (/new Date\(\s*\)/.test(line)) found.push(`${path.relative(SRC, full)}:${i + 1}`)
            })
          }
        }
      }
      walk(SRC)
      if (found.length) this.error(`Use appNow() from src/lib/clock.ts, not new Date() (SS-74a): ${found.join(', ')}`)
    },
  }
}

function checkScopeLevels(): Plugin {
  return {
    name: 'mesiri-check-scope-levels',
    buildStart() {
      const map = fs.readFileSync(path.join(SRC, 'lib/module-map.ts'), 'utf8')
      const levels = fs.readFileSync(path.join(SRC, 'lib/scope-levels.ts'), 'utf8')
      const built = [...map.matchAll(/url: '([^']+)', status: 'built'/g)].map((m) => m[1].split('?')[0])
      const rows = new Set([...levels.matchAll(/\['(\/[^']*)', '(?:site|project|company)'\]/g)].map((m) => m[1]))
      const missing = [...new Set(built)].filter((u) => !rows.has(u))
      if (missing.length) this.error(`Built pages with no row in src/lib/scope-levels.ts: ${missing.join(', ')}`)
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), checkTourMarkers(), checkScopeLevels(), checkOneClock()],
  resolve: {
    alias: {
      '@': SRC,
    },
  },
})
