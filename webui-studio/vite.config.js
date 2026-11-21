import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Built into resource/public/studio, which MoneyPrinterTurbo's API server serves at /studio/.
// `npm run dev` proxies the API and the scene engine to a running server (python main.py).
const api = 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],
  base: '/studio/',
  build: { outDir: '../resource/public/studio', emptyOutDir: true },
  server: { proxy: { '/api': api, '/motion-engine': api } },
});
