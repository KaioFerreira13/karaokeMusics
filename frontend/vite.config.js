import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Evita CORS no desenvolvimento: o front chama /api e o Vite repassa ao FastAPI.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
