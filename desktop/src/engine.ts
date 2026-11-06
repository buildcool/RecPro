import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export interface EngineHandle {
  port: number;
  token: string;
  dataDir: string;
  child: ChildProcess;
  stop(): Promise<void>;
}

export interface EngineOptions {
  dataDir: string;
  dev: boolean;
  repoRoot: string;
  resourcesPath: string;
  logFile: string;
  onExit?(code: number | null): void;
}

/** Starts the local Python engine and resolves once it prints its port. */
export function startEngine(opts: EngineOptions): Promise<EngineHandle> {
  const token = randomBytes(32).toString('hex');
  fs.mkdirSync(opts.dataDir, { recursive: true });
  fs.mkdirSync(path.dirname(opts.logFile), { recursive: true });
  const log = fs.createWriteStream(opts.logFile, { flags: 'a' });

  let cmd: string;
  let args: string[];
  let cwd: string;
  if (opts.dev) {
    cwd = path.join(opts.repoRoot, 'engine');
    cmd = 'uv';
    args = ['run', '--project', cwd, 'python', '-m', 'recpro.server', '--data-dir', opts.dataDir, '--watch-stdin'];
  } else {
    cwd = path.join(opts.resourcesPath, 'engine');
    cmd = path.join(cwd, 'recpro-engine.exe');
    args = ['--data-dir', opts.dataDir, '--watch-stdin'];
  }

  const child = spawn(cmd, args, {
    cwd,
    env: { ...process.env, RECPRO_TOKEN: token, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });

  return new Promise((resolve, reject) => {
    let settled = false;
    let buf = '';
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        killTree(child);
        reject(new Error('The RecPro engine did not start within 120 seconds. See engine.log.'));
      }
    }, 120_000);

    child.stdout!.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      log.write(text);
      if (settled) return;
      buf += text;
      const m = buf.match(/RECPRO_READY (\{.*\})/);
      if (m) {
        settled = true;
        clearTimeout(timer);
        const { port } = JSON.parse(m[1]) as { port: number };
        resolve({
          port,
          token,
          dataDir: opts.dataDir,
          child,
          stop: () => stopChild(child),
        });
      }
    });
    child.stderr!.on('data', (chunk: Buffer) => log.write(chunk));
    child.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });
    child.on('exit', (code) => {
      log.write(`\n[engine exited with code ${code}]\n`);
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`The RecPro engine exited early (code ${code}). See engine.log.`));
      }
      opts.onExit?.(code);
    });
  });
}

function stopChild(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (child.exitCode !== null) return resolve();
    const done = () => resolve();
    child.once('exit', done);
    try {
      child.stdin?.end(); // engine exits when stdin closes
    } catch {
      /* ignore */
    }
    setTimeout(() => {
      if (child.exitCode === null) killTree(child);
      setTimeout(done, 500);
    }, 3000);
  });
}

function killTree(child: ChildProcess) {
  if (child.pid == null) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
  } else {
    child.kill('SIGTERM');
  }
}
