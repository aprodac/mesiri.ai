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
      const wanted = [...tours.matchAll(/target: '([A-Za-z0-9._-]+)'/g)].map((m) => m[1])
      const code = sources(SRC)
        .filter((file) => !file.endsWith(path.join('lib', 'tours.ts')))
        .map((file) => fs.readFileSync(file, 'utf8'))
        .join('\n')
      const missing = wanted.filter((id) => !code.includes(`data-guide="${id}"`) && !code.includes(`guide="${id}"`))
      if (missing.length) {
        this.error(`Tour steps point at markers no element has (src/lib/tours.ts): ${[...new Set(missing)].join(', ')}`)
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
