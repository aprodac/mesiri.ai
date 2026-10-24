import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // INF-15: served at the root of control.mesiri.ai (VITE_BASE=/). The default
  // build keeps the old api.whatsapp.mesiri.ai/mesiriadmin address working
  // until that host redirects to the new one.
  base: process.env.VITE_BASE || '/mesiriadmin/',
})
