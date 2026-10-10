import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development the FastAPI backend runs on :8010; in production it serves this build itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8010',
      '/ws': { target: 'ws://127.0.0.1:8010', ws: true },
    },
  },
  test: { environment: 'node' },
})
