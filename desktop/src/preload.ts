import { contextBridge, ipcRenderer, webUtils } from 'electron';

type EngineInfo = { port: number; token: string; dataDir: string };

const engine = ipcRenderer.sendSync('engine-info-sync') as EngineInfo;

contextBridge.exposeInMainWorld('recpro', {
  engine,
  platform: process.platform,
  pickFolders: (): Promise<string[]> => ipcRenderer.invoke('pick-folders'),
  pickFolder: (title?: string): Promise<string | null> => ipcRenderer.invoke('pick-folder', title),
  pickImages: (): Promise<string[]> => ipcRenderer.invoke('pick-images'),
  showInExplorer: (p: string) => ipcRenderer.send('show-in-explorer', p),
  openPath: (p: string) => ipcRenderer.send('open-path', p),
  startDrag: (paths: string[]) => ipcRenderer.send('start-drag', paths),
  startDragIds: (ids: number[]) => ipcRenderer.send('start-drag-ids', ids),
  notify: (title: string, body: string) => ipcRenderer.send('notify', { title, body }),
  pathForFile: (f: File) => webUtils.getPathForFile(f),
  setDataDir: (dir: string): Promise<EngineInfo> => ipcRenderer.invoke('set-data-dir', dir),
  appInfo: (): Promise<{ version: string; dev: boolean; dataDir: string }> => ipcRenderer.invoke('app-info'),
  onSystemLock: (cb: () => void) => {
    const h = () => cb();
    ipcRenderer.on('system-lock', h);
    return () => ipcRenderer.removeListener('system-lock', h);
  },
  onEngineRestart: (cb: (info: EngineInfo) => void) => {
    const h = (_e: unknown, info: EngineInfo) => cb(info);
    ipcRenderer.on('engine-restarted', h);
    return () => ipcRenderer.removeListener('engine-restarted', h);
  },
  updates: {
    get: () => ipcRenderer.invoke('updates:get'),
    check: () => ipcRenderer.invoke('updates:check'),
    setMode: (mode: string) => ipcRenderer.invoke('updates:mode', mode),
    download: () => ipcRenderer.invoke('updates:download'),
    install: () => ipcRenderer.invoke('updates:install'),
    openPage: () => ipcRenderer.invoke('updates:page'),
    onState: (cb: (s: unknown) => void) => {
      const h = (_e: unknown, s: unknown) => cb(s);
      ipcRenderer.on('updates:state', h);
      return () => ipcRenderer.removeListener('updates:state', h);
    },
  },
});
