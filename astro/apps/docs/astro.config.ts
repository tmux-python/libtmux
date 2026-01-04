import mdx from '@astrojs/mdx'
import react from '@astrojs/react'
import tailwind from '@tailwindcss/vite'
import { defineConfig } from 'astro/config'

export default defineConfig({
  site: 'https://libtmux.git-pull.com',
  integrations: [react(), mdx()],
  server: {
    port: 4350,
  },
  vite: {
    plugins: [tailwind()],
  },
})
