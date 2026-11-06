/** The desktop shell's preload bridge. Absent when the UI runs in a plain browser (dev). */
export type EngineInfo = { port: number; token: string; dataDir: string };

export type UpdateMode = 'auto' | 'notify' | 'off';
export interface UpdateState {
  current: string;
  mode: UpdateMode;
  status: 'idle' | 'checking' | 'latest' | 'available' | 'downloading' | 'ready' | 'error';
  latest: string | null;
  notes: string;
  page: string;
  progress: number;
  error: string | null;
  checkedAt: string | null;
  canInstall: boolean;
  busy: boolean;
}

export interface UpdatesBridge {
  get(): Promise<UpdateState>;
  check(): Promise<UpdateState>;
  setMode(mode: UpdateMode): Promise<UpdateState>;
  download(): Promise<UpdateState>;
  install(): Promise<void>;
  openPage(): Promise<void>;
  onState(cb: (s: UpdateState) => void): () => void;
}

export interface RecproBridge {
  engine: EngineInfo | null;
  platform: string;
  pickFolders(): Promise<string[]>;
  pickFolder(title?: string): Promise<string | null>;
  pickImages(): Promise<string[]>;
  showInExplorer(p: string): void;
  openPath(p: string): void;
  startDrag(paths: string[]): void;
  startDragIds(ids: number[]): void;
  notify(title: string, body: string): void;
  pathForFile(f: File): string;
  setDataDir(dir: string): Promise<EngineInfo>;
  appInfo(): Promise<{ version: string; dev: boolean; dataDir: string }>;
  onSystemLock(cb: () => void): () => void;
  onEngineRestart(cb: (info: EngineInfo) => void): () => void;
  /** Present in the desktop app (older shells may lack it). */
  updates?: UpdatesBridge;
}

declare global {
  interface Window {
    recpro?: RecproBridge;
  }
}

export const bridge: RecproBridge | undefined = typeof window !== 'undefined' ? window.recpro : undefined;
export const isDesktop = !!bridge?.engine;
