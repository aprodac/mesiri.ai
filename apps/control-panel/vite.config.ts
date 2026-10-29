import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// INF-15: served at the root of control.mesiri.ai (VITE_BASE=/). The default
// build keeps the old api.whatsapp.mesiri.ai/mesiriadmin address working
// until that host redirects to the new one.
const base = process.env.VITE_BASE || '/mesiriadmin/'

// Dev server only: /mesiriadmin (no slash) redirects to /mesiriadmin/
// instead of Vite's "did you mean" page.
const baseRedirect: Plugin = {
  name: 'base-redirect',
  configureServer(server) {
    const bare = base.replace(/\/$/, '')
    server.middlewares.use((req, res, next) => {
      const [path, query] = (req.url ?? '').split('?')
      if (bare && path === bare) {
        res.statusCode = 302
        res.setHeader('Location', base + (query ? `?${query}` : ''))
        res.end()
        return
      }
      next()
    })
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), baseRedirect],
  base,
})
