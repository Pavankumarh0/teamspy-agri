import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // three.js + the scene are split into a lazily loaded chunk behind the preloader
    chunkSizeWarningLimit: 1200,
  },
})
