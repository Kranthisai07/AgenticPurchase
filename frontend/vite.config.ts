import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/sessions': 'http://localhost:8000',
      '/saga': 'http://localhost:8000',
      '/checkout': 'http://localhost:8000',
      '/webhooks': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
