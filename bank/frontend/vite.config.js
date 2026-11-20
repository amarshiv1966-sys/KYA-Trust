import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The pages and the API share one origin: Vite forwards /api to FastAPI,
// so the session cookie just works and there is no CORS to configure.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // reachable from Prachi's Mac on the same Wi-Fi
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
