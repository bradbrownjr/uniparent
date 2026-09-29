import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, API calls go to a locally running backend (python -m uniparent serve).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8095' } },
  // ~170 KB gzipped (React + MUI) is fine for a LAN app; no code splitting needed.
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 800 },
})
