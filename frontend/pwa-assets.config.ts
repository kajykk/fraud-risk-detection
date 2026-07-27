import { defineConfig, minimal2023Preset } from '@vite-pwa/assets-generator/config'

export default defineConfig({
  preset: {
    ...minimal2023Preset,
    maskable: { padding: 0.1, resizeOptions: { background: '#0b5fff' } },
    transparent: { sizes: [192, 512] }
  },
  images: ['public/pwa-source.svg']
})
