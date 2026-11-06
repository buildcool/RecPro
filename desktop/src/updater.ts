// Updates from RecPro's GitHub Releases. The only thing sent is the request for the latest release
// (GitHub sees the app's version and your IP address): never photos, file names, faces or text.
//   auto   — check on start and once a day, download in the background, ask "Restart to update"
//   notify — check the same way and show what's new; downloading and installing are your call
//   off    — RecPro never asks the internet about updates (you can still check by hand)
// Strict offline (Settings → Network) stops every check, automatic or by hand.
// Only the installed app can update itself; a development run just points to the releases page.
import { app, ipcMain, shell, type BrowserWindow, type IpcMainInvokeEvent } from 'electron';
import fs from 'node:fs';
import https from 'node:https';
import path from 'node:path';

const OWNER = 'buildcool';
const REPO = 'RecPro';
const PAGE = `https://github.com/${OWNER}/${REPO}/releases/latest`;
const DAY = 24 * 60 * 60 * 1000;
export const MODES = ['auto', 'notify', 'off'] as const;
export type Mode = (typeof MODES)[number];
type Status = 'idle' | 'checking' | 'latest' | 'available' | 'downloading' | 'ready' | 'error';

export interface UpdateState {
  current: string;
  mode: Mode;
  status: Status;
  latest: string | null;
  notes: string;
  page: string;
  progress: number;
  error: string | null;
  checkedAt: string | null;
  canInstall: boolean;
  busy: boolean;
}

export interface UpdaterOptions {
  /** Strict offline is on: no update checks at all. */
  isOffline(): Promise<boolean>;
  /** Only the app's own pages may drive the updater. */
  allowed(e: IpcMainInvokeEvent): boolean;
}

interface Updater {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  logger: unknown;
  on(event: string, cb: (arg: any) => void): unknown;
  checkForUpdates(): Promise<unknown>;
  downloadUpdate(): Promise<unknown>;
  quitAndInstall(isSilent?: boolean, isForceRunAfter?: boolean): void;
}

let win: BrowserWindow | null = null;
let updater: Updater | null = null;
let timer: NodeJS.Timeout | null = null;
let opts: UpdaterOptions | null = null;
const state: UpdateState = {
  current: app.getVersion(),
  mode: 'notify',
  status: 'idle',
  latest: null,
  notes: '',
  page: PAGE,
  progress: 0,
  error: null,
  checkedAt: null,
  canInstall: false,
  busy: false,
};

const settingsFile = () => path.join(app.getPath('userData'), 'updates.json');

function load() {
  try {
    const s = JSON.parse(fs.readFileSync(settingsFile(), 'utf8')) as Partial<UpdateState>;
    if (s.mode && (MODES as readonly string[]).includes(s.mode)) state.mode = s.mode;
    if (s.checkedAt) state.checkedAt = s.checkedAt;
  } catch {
    /* first run: notify */
  }
}

function save() {
  try {
    fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
    fs.writeFileSync(settingsFile(), JSON.stringify({ mode: state.mode, checkedAt: state.checkedAt }, null, 1));
  } catch {
    /* read-only profile: the setting lasts this session */
  }
}

function push(patch: Partial<UpdateState> = {}) {
  Object.assign(state, patch);
  if (win && !win.isDestroyed()) win.webContents.send('updates:state', { ...state });
}

/** True when version a is newer than b ("0.10.0" > "0.9.0", not a string compare). */
export function newer(a: string, b: string): boolean {
  const pa = String(a).replace(/^v/, '').split(/[.-]/).map((x) => parseInt(x, 10) || 0);
  const pb = String(b).replace(/^v/, '').split(/[.-]/).map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  }
  return false;
}

/** Release notes as plain text: electron-updater hands over HTML, the API markdown. */
export function plain(notes: unknown): string {
  let s: unknown = notes;
  if (Array.isArray(s)) s = s.map((n: { note?: string }) => n?.note || '').join('\n\n');
  return String(s || '')
    .replace(/<\/(p|li|h\d)>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .trim()
    .slice(0, 4000);
}

function latestFromApi(): Promise<{ version: string; notes: string; page: string }> {
  // the latest release straight from GitHub's API (a run that can't install itself only needs to know)
  return new Promise((resolve, reject) => {
    const req = https.get(
      {
        host: 'api.github.com',
        path: `/repos/${OWNER}/${REPO}/releases/latest`,
        headers: { 'User-Agent': `RecPro/${state.current}`, Accept: 'application/vnd.github+json' },
        timeout: 15000,
      },
      (res) => {
        let body = '';
        res.on('data', (d) => (body += d));
        res.on('end', () => {
          if (res.statusCode !== 200) return reject(new Error(`GitHub answered ${res.statusCode}`));
          try {
            const r = JSON.parse(body) as { tag_name?: string; body?: string; html_url?: string };
            resolve({ version: String(r.tag_name || '').replace(/^v/, ''), notes: r.body || '', page: r.html_url || PAGE });
          } catch (e) {
            reject(e as Error);
          }
        });
      },
    );
    req.on('timeout', () => req.destroy(new Error('no answer from GitHub')));
    req.on('error', reject);
  });
}

async function setupUpdater() {
  if (!app.isPackaged || process.platform !== 'win32') return; // only the installed app can replace itself
  // the installer writes app-update.yml; an unpacked build has none and only points to the page
  if (!fs.existsSync(path.join(process.resourcesPath, 'app-update.yml'))) return;
  try {
    const mod = await import('electron-updater');
    updater = (mod.autoUpdater ?? (mod as unknown as { default: { autoUpdater: Updater } }).default.autoUpdater) as unknown as Updater;
  } catch {
    updater = null;
    return;
  }
  state.canInstall = true;
  updater.autoDownload = false; // decided per check from the mode
  updater.autoInstallOnAppQuit = true; // a downloaded update goes in the next time you close RecPro
  updater.logger = null;
  updater.on('update-available', (i: { version: string; releaseNotes?: unknown }) =>
    push({ status: 'available', latest: i.version, notes: plain(i.releaseNotes) }),
  );
  updater.on('update-not-available', () => push({ status: 'latest', latest: state.current }));
  updater.on('download-progress', (p: { percent?: number }) => push({ status: 'downloading', progress: Math.round(p.percent || 0) }));
  updater.on('update-downloaded', (i: { version: string }) => push({ status: 'ready', latest: i.version, progress: 100 }));
  updater.on('error', (e: unknown) => push({ status: 'error', error: friendly(e), busy: false }));
}

export function friendly(e: unknown): string {
  const m = String((e as Error)?.message || e || '');
  if (/ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ETIMEDOUT|no answer|net::/i.test(m)) return 'No internet connection. Try again later.';
  if (/No published versions/i.test(m)) return 'No RecPro release has been published yet.';
  if (/404|latest\.yml/i.test(m)) return 'The latest release has no update file for this build yet. Download it from the releases page.';
  return m.split('\n')[0].slice(0, 200);
}

async function check({ manual = false } = {}): Promise<UpdateState> {
  if (state.busy || state.status === 'downloading' || state.status === 'ready') return { ...state };
  if (state.mode === 'off' && !manual) return { ...state };
  if (await opts?.isOffline().catch(() => false)) {
    if (manual) push({ status: 'error', error: 'Strict offline is on (Settings → Network), so RecPro does not contact GitHub.' });
    return { ...state };
  }
  push({ status: 'checking', error: null, busy: true });
  try {
    if (updater) {
      updater.autoDownload = state.mode === 'auto';
      await updater.checkForUpdates();
      if (state.status === 'checking') push({ status: 'latest', latest: state.current });
    } else {
      const r = await latestFromApi();
      push(
        newer(r.version, state.current)
          ? { status: 'available', latest: r.version, notes: plain(r.notes), page: r.page }
          : { status: 'latest', latest: r.version },
      );
    }
  } catch (e) {
    push({ status: 'error', error: friendly(e) });
  }
  state.checkedAt = new Date().toISOString();
  save();
  push({ busy: false });
  return { ...state };
}

function schedule() {
  if (timer) clearTimeout(timer);
  if (state.mode === 'off') return;
  const last = state.checkedAt ? Date.parse(state.checkedAt) : 0;
  const wait = Math.max(15000, last + DAY - Date.now()); // not in the first seconds of start-up, then once a day
  timer = setTimeout(async () => {
    await check();
    schedule();
  }, Math.min(wait, DAY));
}

export function init(window: BrowserWindow, options: UpdaterOptions) {
  win = window;
  opts = options;
  load();
  void setupUpdater();
  const guard =
    <T>(fn: (e: IpcMainInvokeEvent, ...args: any[]) => T) =>
    (e: IpcMainInvokeEvent, ...args: any[]) =>
      options.allowed(e) ? fn(e, ...args) : null;
  ipcMain.handle('updates:get', guard(() => ({ ...state })));
  ipcMain.handle('updates:check', guard(() => check({ manual: true })));
  ipcMain.handle(
    'updates:mode',
    guard((_e, mode: string) => {
      if ((MODES as readonly string[]).includes(mode)) {
        state.mode = mode as Mode;
        save();
        push();
        schedule();
        if (mode === 'auto' && updater && state.status === 'available') {
          updater.downloadUpdate().catch((err) => push({ status: 'error', error: friendly(err) }));
        }
      }
      return { ...state };
    }),
  );
  ipcMain.handle(
    'updates:download',
    guard(() => {
      if (!updater) {
        void shell.openExternal(state.page);
        return { ...state };
      }
      if (state.status !== 'available') return { ...state };
      push({ status: 'downloading', progress: 0 });
      updater.downloadUpdate().catch((err) => push({ status: 'error', error: friendly(err) }));
      return { ...state };
    }),
  );
  ipcMain.handle(
    'updates:install',
    guard(() => {
      // only on your click: RecPro closes (the engine with it), installs, and opens again
      if (updater && state.status === 'ready') setImmediate(() => updater?.quitAndInstall(true, true));
      return null;
    }),
  );
  ipcMain.handle('updates:page', guard(() => shell.openExternal(state.page)));
  schedule();
}
