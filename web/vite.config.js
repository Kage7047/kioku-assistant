import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into the API's static folder and served same-origin by FastAPI: no CORS, no second
// service. `npm run dev` proxies API calls to a local Kioku on :8000.
const api = ['/status', '/runs', '/tasks', '/approvals', '/writes', '/skills', '/people', '/pause',
  '/resume', '/ingest', '/health', '/handoffs', '/budget', '/inbox']

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: { outDir: '../src/kioku/api/static', emptyOutDir: true, sourcemap: false },
  server: { proxy: Object.fromEntries(api.map((p) => [p, 'http://localhost:8000'])) },
})
