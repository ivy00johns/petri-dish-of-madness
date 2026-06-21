import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Read the SAME root .env the backend uses; only VITE_*-prefixed vars are
  // injected into the client bundle, so backend secrets stay server-side.
  envDir: '../',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      // Wave I / EM-210 — the Atelier's generated PNGs are served by the backend
      // StaticFiles mount at /assets/images/<id>.png (an external side-artifact,
      // off the replay surface). Proxy it in dev so the relative gallery urls
      // resolve to real art on :5173 — without this the GalleryPanel thumbnails
      // and the 3D PlazaBanner texture both fall back to placeholders locally.
      '/assets': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
