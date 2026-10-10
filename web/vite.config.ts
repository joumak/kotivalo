
/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// During `npm run dev` the API comes from a local `kotivalo serve --fake` (default),
// or from the Pi: KOTIVALO_API=http://kotivalo.local:8080 npm run dev
const api = process.env.KOTIVALO_API ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/', // the Python service serves the build under /static/
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  build: {
    // Served by the Python service; gitignored, rebuilt by deploy/deploy.sh.
    outDir: '../src/kotivalo/static',
    emptyOutDir: true,
  },
  server: { proxy: { '/api': { target: api, changeOrigin: true } } },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },
})
