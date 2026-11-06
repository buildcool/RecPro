// Starts the full app for development: Vite (UI) + esbuild watch (desktop) + Electron.
// Electron launches the Python engine itself via `uv run`.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const isWin = process.platform === 'win32';
const npm = isWin ? 'npm.cmd' : 'npm';
const children = [];

function run(cmd, args, opts = {}) {
  const child = spawn(cmd, args, { cwd: root, stdio: 'inherit', shell: isWin, ...opts });
  children.push(child);
  return child;
}

async function waitFor(url, timeoutMs = 60000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function shutdown(code = 0) {
  for (const c of children) {
    try {
      if (isWin && c.pid) spawn('taskkill', ['/pid', String(c.pid), '/T', '/F'], { stdio: 'ignore' });
      else c.kill('SIGTERM');
    } catch {
      /* ignore */
    }
  }
  process.exit(code);
}
process.on('SIGINT', () => shutdown(0));

const devUrl = 'http://localhost:5173';
run(npm, ['run', 'dev', '-w', 'ui']);
await new Promise((resolve, reject) => {
  const b = spawn(npm, ['run', 'build', '-w', 'desktop'], { cwd: root, stdio: 'inherit', shell: isWin });
  b.on('exit', (code) => (code === 0 ? resolve() : reject(new Error('desktop build failed'))));
});
run(npm, ['run', 'watch', '-w', 'desktop']);
await waitFor(devUrl);

const require = createRequire(path.join(root, 'desktop', 'package.json'));
const electron = require('electron');
const app = run(electron, ['.'], {
  cwd: path.join(root, 'desktop'),
  shell: false,
  env: {
    ...process.env,
    RECPRO_DEV_URL: devUrl,
    RECPRO_DATA_DIR: process.env.RECPRO_DATA_DIR || path.join(root, '.devdata'),
  },
});
app.on('exit', (code) => shutdown(code ?? 0));
