import typography from '@tailwindcss/typography'
import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{astro,ts,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        ink: 'oklch(var(--color-ink) / <alpha-value>)',
        paper: 'oklch(var(--color-paper) / <alpha-value>)',
        accent: 'oklch(var(--color-accent) / <alpha-value>)',
        accentTwo: 'oklch(var(--color-accent-two) / <alpha-value>)',
        moss: 'oklch(var(--color-moss) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['"Space Grotesk"', 'ui-sans-serif', 'sans-serif'],
        serif: ['"Fraunces"', 'ui-serif', 'serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 20px 60px -30px oklch(var(--color-accent) / 0.5)',
      },
    },
  },
  plugins: [typography],
}

export default config
