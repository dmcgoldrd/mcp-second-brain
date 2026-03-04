import { defineConfig } from 'vite'

export default defineConfig({
  root: '.',
  build: {
    outDir: 'dist',
    target: 'es2020',
  },
  server: {
    port: 3000,
    open: true,
  },
  // SPA fallback: serve index.html for /oauth/consent (OAuth redirect path)
  appType: 'spa',
})
