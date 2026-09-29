import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy all API calls to the FastAPI backend during development.
    proxy: {
      '/health':          'http://localhost:8000',
      '/analyze':         'http://localhost:8000',
      '/feedback':        'http://localhost:8000',
      '/deployments':     'http://localhost:8000',
      '/memory':          'http://localhost:8000',
    },
  },
})
