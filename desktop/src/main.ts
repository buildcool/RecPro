import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  nativeTheme,
  net,
  Notification,
  powerMonitor,
  protocol,
  shell,
  type IpcMainEvent,
  type IpcMainInvokeEvent,
} from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { startEngine, type EngineHandle } from './engine';

const DEV_URL = process.env.RECPRO_DEV_URL || '';
const isDev = DEV_URL !== '';
const repoRoot = path.resolve(__dirname, '..', '..');
const uiDist = isDev ? '' : path.join(process.resourcesPath, 'ui');

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

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
  {
    scheme: 'recpro-media',
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true },
  },
]);

let engine: EngineHandle | null = null;
let win: BrowserWindow | null = null;
let quitting = false;

// ---- config -----------------------------------------------------------------
type AppConfig = { dataDir?: string };
const configPath = () => path.join(app.getPath('userData'), 'config.json');

function readConfig(): AppConfig {
  try {
    return JSON.parse(fs.readFileSync(configPath(), 'utf8')) as AppConfig;
  } catch {
    return {};
  }
}

function writeConfig(cfg: AppConfig) {
  fs.mkdirSync(path.dirname(configPath()), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2));
}

function defaultDataDir(): string {
  if (process.env.RECPRO_DATA_DIR) return path.resolve(process.env.RECPRO_DATA_DIR);
  const cfg = readConfig();
  if (cfg.dataDir) return cfg.dataDir;
  if (process.platform === 'win32' && fs.existsSync('D:\\')) return 'D:\\RecProData';
  return path.join(app.getPath('userData'), 'data');
}

// ---- engine -----------------------------------------------------------------
async function launchEngine(dataDir: string): Promise<EngineHandle> {
  return startEngine({
    dataDir,
    dev: isDev,
    repoRoot,
    resourcesPath: process.resourcesPath,
    logFile: path.join(dataDir, 'logs', 'desktop-engine.log'),
    onExit: (code) => {
      if (!quitting && win) {
        dialog.showErrorBox(
          'RecPro engine stopped',
          `The local engine stopped unexpectedly (code ${code}). RecPro will close. Your files are safe; any copy in progress resumes next time.`,
        );
        app.quit();
      }
    },
  });
}

function engineUrl(p: string): string {
  if (!engine) throw new Error('engine not running');
  return `http://127.0.0.1:${engine.port}/${p.replace(/^\/+/, '')}`;
}

// ---- protocols --------------------------------------------------------------
function registerProtocols() {
  protocol.handle('recpro-media', async (req) => {
    const u = new URL(req.url);
    const target = engineUrl(u.pathname + u.search);
    const headers: Record<string, string> = { 'X-RecPro-Token': engine!.token };
    const range = req.headers.get('range');
    if (range) headers.Range = range;
    return net.fetch(target, { method: 'GET', headers });
  });

  protocol.handle('app', async (req) => {
    const u = new URL(req.url);
    let rel = decodeURIComponent(u.pathname);
    if (rel === '/' || rel === '') rel = '/index.html';
    const file = path.normalize(path.join(uiDist, rel));
    if (!file.startsWith(uiDist)) return new Response('Not found', { status: 404 });
    const target = fs.existsSync(file) ? file : path.join(uiDist, 'index.html');
    const res = await net.fetch(pathToFileURL(target).toString());
    const headers = new Headers(res.headers);
    if (target.endsWith('.html')) headers.set('Content-Security-Policy', CSP);
    return new Response(res.body, { status: res.status, headers });
  });
}

// ---- window -----------------------------------------------------------------
function iconPath() {
  return path.join(__dirname, '..', 'assets', 'icon.png');
}

function createWindow() {
  const dark = nativeTheme.shouldUseDarkColors;
  win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    title: 'RecPro',
    backgroundColor: dark ? '#121212' : '#f6f6f4',
    icon: fs.existsSync(iconPath()) ? iconPath() : undefined,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });
  win.once('ready-to-show', () => win?.show());
  win.on('closed', () => (win = null));

  // Never navigate away from the app or open other windows.
  win.webContents.on('will-navigate', (e, url) => {
    if (!isAppUrl(url)) e.preventDefault();
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  if (isDev) {
    win.webContents.on('before-input-event', (_e, input) => {
      if (input.type === 'keyDown' && input.control && input.shift && input.key.toLowerCase() === 'i') {
        win?.webContents.toggleDevTools();
      }
    });
    void win.loadURL(DEV_URL);
  } else {
    void win.loadURL('app://ui/index.html');
  }
}

function isAppUrl(url: string) {
  return url.startsWith('app://ui/') || (isDev && url.startsWith(DEV_URL));
}

function fromApp(e: IpcMainEvent | IpcMainInvokeEvent): boolean {
  const url = e.senderFrame?.url ?? '';
  return isAppUrl(url);
}

// ---- IPC --------------------------------------------------------------------
function registerIpc() {
  ipcMain.on('engine-info-sync', (e) => {
    e.returnValue = engine ? { port: engine.port, token: engine.token, dataDir: engine.dataDir } : null;
  });

  ipcMain.handle('app-info', (e) => {
    if (!fromApp(e)) return null;
    return { version: app.getVersion(), dev: isDev, dataDir: engine?.dataDir ?? '' };
  });

  ipcMain.handle('pick-folders', async (e) => {
    if (!fromApp(e) || !win) return [];
    const r = await dialog.showOpenDialog(win, {
      title: 'Choose folders with photos and videos',
      properties: ['openDirectory', 'multiSelections'],
    });
    return r.canceled ? [] : r.filePaths;
  });

  ipcMain.handle('pick-folder', async (e, title?: string) => {
    if (!fromApp(e) || !win) return null;
    const r = await dialog.showOpenDialog(win, {
      title: title || 'Choose a folder',
      properties: ['openDirectory', 'createDirectory', 'promptToCreate'],
    });
    return r.canceled ? null : r.filePaths[0] ?? null;
  });

  ipcMain.handle('pick-images', async (e) => {
    if (!fromApp(e) || !win) return [];
    const r = await dialog.showOpenDialog(win, {
      title: 'Choose photos of the person',
      properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'Images', extensions: ['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'bmp', 'tif', 'tiff'] }],
    });
    return r.canceled ? [] : r.filePaths;
  });

  ipcMain.on('show-in-explorer', (e, p: string) => {
    if (fromApp(e) && typeof p === 'string') shell.showItemInFolder(p);
  });

  ipcMain.on('open-path', (e, p: string) => {
    if (fromApp(e) && typeof p === 'string') void shell.openPath(p);
  });

  ipcMain.on('start-drag', (e, paths: string[]) => {
    if (!fromApp(e) || !Array.isArray(paths) || paths.length === 0) return;
    const files = paths.filter((p) => typeof p === 'string' && fs.existsSync(p));
    if (files.length === 0) return;
    const icon = fs.existsSync(path.join(__dirname, '..', 'assets', 'drag.png'))
      ? nativeImage.createFromPath(path.join(__dirname, '..', 'assets', 'drag.png'))
      : nativeImage.createEmpty();
    e.sender.startDrag({ file: files[0], files, icon });
  });

  // Drag selected library items out of the app: the main process resolves their paths.
  ipcMain.on('start-drag-ids', async (e, ids: number[]) => {
    if (!fromApp(e) || !engine || !Array.isArray(ids) || ids.length === 0) return;
    try {
      const res = await net.fetch(engineUrl('api/media/paths'), {
        method: 'POST',
        headers: { 'X-RecPro-Token': engine.token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: ids.slice(0, 5000) }),
      });
      const map = (await res.json()) as Record<string, string>;
      const files = Object.values(map).filter((p) => fs.existsSync(p));
      if (files.length === 0) return;
      const iconFile = path.join(__dirname, '..', 'assets', 'drag.png');
      const icon = fs.existsSync(iconFile) ? nativeImage.createFromPath(iconFile) : nativeImage.createEmpty();
      e.sender.startDrag({ file: files[0], files, icon });
    } catch {
      /* drag simply doesn't start */
    }
  });

  ipcMain.on('notify', (e, msg: { title: string; body: string }) => {
    if (!fromApp(e) || !Notification.isSupported()) return;
    new Notification({ title: String(msg?.title ?? 'RecPro'), body: String(msg?.body ?? ''), silent: false }).show();
  });

  ipcMain.handle('set-data-dir', async (e, dir: string) => {
    if (!fromApp(e) || typeof dir !== 'string' || !dir) return null;
    const target = path.resolve(dir);
    fs.mkdirSync(target, { recursive: true });
    quitting = true; // suppress the "engine stopped" dialog during the planned restart
    await engine?.stop();
    quitting = false;
    engine = await launchEngine(target);
    writeConfig({ ...readConfig(), dataDir: target });
    const info = { port: engine.port, token: engine.token, dataDir: engine.dataDir };
    win?.webContents.send('engine-restarted', info);
    return info;
  });
}

// ---- lifecycle --------------------------------------------------------------
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    registerProtocols();
    registerIpc();
    try {
      engine = await launchEngine(defaultDataDir());
    } catch (err) {
      dialog.showErrorBox('RecPro could not start', String((err as Error)?.message ?? err));
      app.quit();
      return;
    }
    createWindow();
    powerMonitor.on('lock-screen', () => win?.webContents.send('system-lock'));
    powerMonitor.on('suspend', () => win?.webContents.send('system-lock'));
  });

  app.on('before-quit', async (e) => {
    if (quitting) return;
    quitting = true;
    if (engine) {
      e.preventDefault();
      await engine.stop();
      engine = null;
      app.quit();
    }
  });

  app.on('window-all-closed', () => app.quit());
}
