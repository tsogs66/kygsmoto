import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'icon-192.png', 'icon-512.png',
                      'icon-maskable-512.png'],
      workbox: {
        // Default globs miss woff2, which would leave an installed app
        // re-fetching its own fonts on every cold start.
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
      },
      manifest: {
        name: 'KYGSMOTO Sales & Inventory',
        short_name: 'KYGSMOTO',
        description: 'Motorshop sales, inventory, and reporting',
        theme_color: '#171e26',
        background_color: '#0f1419',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        icons: [
          { src: 'favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          // Separate art: a launcher may crop a maskable icon to a circle, and
          // the sprocket's teeth run to the edge of the 'any' tile.
          { src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png',
            purpose: 'maskable' },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
