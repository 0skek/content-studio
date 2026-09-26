import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend; the dev server proxies API and media paths to it, so no CORS setup is needed.
// BACKEND_URL overrides it, e.g. to point a second dev server at a test backend.
const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000'
const BACKEND_PATHS = ['/briefs', '/posts', '/channels', '/media', '/health', '/clock', '/publisher', '/adapters', '/feeds', '/reports', '/insights']

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(BACKEND_PATHS.map((path) => [path, BACKEND_URL])),
  },
})
