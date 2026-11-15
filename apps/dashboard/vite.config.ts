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
      // The page tours and the walkthroughs (SS-42, src/lib/walkthroughs.ts) point at markers the same way.
      const files = ['lib/tours.ts', 'lib/walkthroughs.ts']
      const guides = files.map((f) => fs.readFileSync(path.join(SRC, f), 'utf8')).join('\n')
      const wanted = [...guides.matchAll(/target: '([A-Za-z0-9._-]+)'/g)].map((m) => m[1])
      const code = sources(SRC)
        .filter((file) => !files.some((f) => file.endsWith(path.join(...f.split('/')))))
        .map((file) => fs.readFileSync(file, 'utf8'))
        .join('\n')
      const missing = wanted.filter((id) => !code.includes(`data-guide="${id}"`) && !code.includes(`guide="${id}"`))
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
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), checkTourMarkers()],
  resolve: {
    alias: {
      '@': SRC,
    },
  },
})
