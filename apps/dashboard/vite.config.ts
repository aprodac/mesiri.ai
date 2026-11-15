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
      const tours = fs.readFileSync(path.join(SRC, 'lib/tours.ts'), 'utf8')
      const wanted = [
        ...[...tours.matchAll(/target: '([A-Za-z0-9._-]+)'/g)].map((m) => m[1]),
        // A tour's startWhen markers (the page's content it waits for) must exist too.
        ...[...tours.matchAll(/startWhen: \[([^\]]*)\]/g)].flatMap((m) => [...m[1].matchAll(/'([A-Za-z0-9._-]+)'/g)].map((x) => x[1])),
      ]
      const code = sources(SRC)
        .filter((file) => !file.endsWith(path.join('lib', 'tours.ts')))
        .map((file) => fs.readFileSync(file, 'utf8'))
        .join('\n')
      // A marker as text (data-guide="x", guide="x") or set by a condition (data-guide={next ? 'x' : undefined}).
      const has = (id: string) =>
        code.includes(`data-guide="${id}"`) || code.includes(`guide="${id}"`) || new RegExp(`guide=\\{[^}]*'${id.replace(/\./g, '\\.')}'`).test(code)
      const missing = wanted.filter((id) => !has(id))
      if (missing.length) {
        this.error(`Tour steps point at markers no element has (src/lib/tours.ts): ${[...new Set(missing)].join(', ')}`)
      }
    },
  }
}

// SCP-07: every built page of the module map has its row in lib/scope-levels.ts (how far it narrows to the project
// or site picked). The page's console error only shows in the screenshot run, and four pages slipped past it, so
// the build checks it too.
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
  plugins: [react(), tailwindcss(), checkTourMarkers(), checkScopeLevels()],
  resolve: {
    alias: {
      '@': SRC,
    },
  },
})
