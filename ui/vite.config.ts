import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The production build gets a strict Content-Security-Policy: no remote scripts, styles,
// fonts or connections. Only the local engine (127.0.0.1) and the app's own protocols.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: recpro-media:",
  "media-src 'self' blob: recpro-media:",
  "font-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-src 'none'",
].join('; ');

function cspPlugin(): Plugin {
  return {
    name: 'recpro-csp',
    apply: 'build',
    transformIndexHtml(html) {
      return html.replace('<head>', `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`);
    },
  };
}

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), cspPlugin()],
  server: { port: 5173, strictPort: true },
  build: { outDir: 'dist', emptyOutDir: true, target: 'chrome130', chunkSizeWarningLimit: 1500 },
  test: { environment: 'jsdom' },
} as never);
