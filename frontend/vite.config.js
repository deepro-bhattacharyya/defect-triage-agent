import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During `npm run dev`, the Vite dev server (5173) proxies API calls to the
// FastAPI backend (8000), so the browser stays same-origin and there's no CORS.
// `npm run build` emits static files to dist/, which the backend serves in prod.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/triage': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
})
