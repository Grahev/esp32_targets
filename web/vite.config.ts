import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

// `npm run dev` proxies the API to a hub at HUB (default 192.168.4.1), so the
// app can be developed on a laptop joined to the hub's WiFi.
const hub = process.env.HUB || 'http://192.168.4.1';

export default defineConfig({
  plugins: [preact()],
  build: { target: 'es2019', assetsInlineLimit: 100000, cssCodeSplit: false, modulePreload: false },
  server: { proxy: { '/api': hub, '/ws': { target: hub.replace('http', 'ws'), ws: true } } },
});
