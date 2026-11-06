/** The desktop shell's preload bridge. Absent when the UI runs in a plain browser (dev). */
export type EngineInfo = { port: number; token: string; dataDir: string };

export interface RecproBridge {
  engine: EngineInfo | null;
  platform: string;
  pickFolders(): Promise<string[]>;
  pickFolder(title?: string): Promise<string | null>;
  pickImages(): Promise<string[]>;
  showInExplorer(p: string): void;
  openPath(p: string): void;
  startDrag(paths: string[]): void;
  notify(title: string, body: string): void;
  pathForFile(f: File): string;
  setDataDir(dir: string): Promise<EngineInfo>;
  appInfo(): Promise<{ version: string; dev: boolean; dataDir: string }>;
  onSystemLock(cb: () => void): () => void;
  onEngineRestart(cb: (info: EngineInfo) => void): () => void;
}

declare global {
  interface Window {
    recpro?: RecproBridge;
  }
}

export const bridge: RecproBridge | undefined = typeof window !== 'undefined' ? window.recpro : undefined;
export const isDesktop = !!bridge?.engine;
