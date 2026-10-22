import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  base: './',
  plugins: [tailwindcss()],
  resolve: {alias: {'@': fileURLToPath(new URL('./src', import.meta.url))}},
  build: {assetsInlineLimit: 0, outDir: '../manager/static', emptyOutDir: true, sourcemap: false, rolldownOptions: {onLog(level,log,handler){if(log.code==='MODULE_LEVEL_DIRECTIVE')return;handler(level,log)}}},
})
