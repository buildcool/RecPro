import { toast } from 'sonner';
import { post } from '../../lib/api';
import { bridge } from '../../lib/bridge';
import { create } from 'zustand';

/** In browser dev mode there is no native picker; a folder browser dialog is used instead. */
export const useFolderBrowser = create<{ open: boolean; resolve: ((paths: string[]) => void) | null; ask: () => Promise<string[]> }>(
  (set) => ({
    open: false,
    resolve: null,
    ask: () =>
      new Promise<string[]>((resolve) => {
        set({ open: true, resolve: (paths) => { set({ open: false, resolve: null }); resolve(paths); } });
      }),
  }),
);

export async function pickFolders(): Promise<string[]> {
  if (bridge?.engine) return bridge.pickFolders();
  return useFolderBrowser.getState().ask();
}

export async function addFolders(paths: string[]) {
  if (paths.length === 0) return;
  const res = await post<{ added: { id: number; path: string }[]; skipped: { path: string; reason: string }[] }>('/api/folders', {
    paths,
  });
  if (res.added.length) toast.success(res.added.length === 1 ? `Added ${res.added[0].path}` : `Added ${res.added.length} folders`, {
    description: 'Photos appear in a few seconds. Faces and categories follow in the background.',
  });
  res.skipped.forEach((s) => toast.message(`Skipped ${s.path}`, { description: s.reason }));
}

export async function addFoldersFlow() {
  try {
    const paths = await pickFolders();
    await addFolders(paths);
  } catch (e) {
    toast.error((e as Error).message);
  }
}
