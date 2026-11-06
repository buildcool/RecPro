import { useQuery } from '@tanstack/react-query';
import { ChevronRight, Folder, HardDrive, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { Button, Modal, Spinner } from '../../components/ui';
import { get, qs } from '../../lib/api';
import { bytes } from '../../lib/format';
import { useFolderBrowser } from './addFolders';

type Listing = { path: string; parent: string | null; dirs: { name: string; path: string }[] };
type Drive = { path: string; total: number | null; free: number | null };

/** Fallback folder picker for the browser dev mode (the desktop app uses the native dialog). */
export function FolderBrowserDialog() {
  const { open, resolve } = useFolderBrowser();
  const [path, setPath] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const drives = useQuery({ queryKey: ['fs', 'drives'], queryFn: () => get<Drive[]>('/api/fs/drives'), enabled: open });
  const listing = useQuery({
    queryKey: ['fs', 'list', path],
    queryFn: () => get<Listing>(`/api/fs/list${qs({ path })}`),
    enabled: open && !!path,
  });

  const finish = (paths: string[]) => {
    resolve?.(paths);
    setPicked([]);
    setPath(null);
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && finish([])}
      title="Choose folders"
      description="Pick one or more folders with photos and videos."
      width="max-w-xl"
      footer={
        <>
          <span className="mr-auto text-xs text-fg-3">{picked.length ? `${picked.length} chosen` : ''}</span>
          <Button variant="ghost" onClick={() => finish([])}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!picked.length && !path} onClick={() => finish(picked.length ? picked : path ? [path] : [])}>
            {picked.length ? `Add ${picked.length}` : 'Add this folder'}
          </Button>
        </>
      }
    >
      <div className="mb-2 flex items-center gap-2 text-xs text-fg-2">
        {path ? (
          <>
            <button type="button" className="rounded p-1 hover:bg-surface-2" onClick={() => setPath(listing.data?.parent ?? null)} aria-label="Up">
              <Undo2 className="size-4" />
            </button>
            <span className="truncate font-medium text-fg">{path}</span>
          </>
        ) : (
          'This PC'
        )}
      </div>
      <div className="h-80 overflow-y-auto rounded-xl border border-line">
        {!path &&
          drives.data?.map((d) => (
            <button key={d.path} type="button" onClick={() => setPath(d.path)} className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-surface-2">
              <HardDrive className="size-4 text-fg-3" />
              <span className="flex-1">{d.path}</span>
              <span className="text-xs text-fg-3">{d.free != null ? `${bytes(d.free)} free` : ''}</span>
            </button>
          ))}
        {path && listing.isLoading && (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        )}
        {path &&
          listing.data?.dirs.map((d) => (
            <div key={d.path} className="flex items-center gap-2 px-2 py-1 hover:bg-surface-2">
              <input
                type="checkbox"
                className="size-4 accent-[var(--accent)]"
                checked={picked.includes(d.path)}
                onChange={(e) => setPicked((p) => (e.target.checked ? [...p, d.path] : p.filter((x) => x !== d.path)))}
                aria-label={`Choose ${d.name}`}
              />
              <button type="button" onClick={() => setPath(d.path)} className="flex flex-1 items-center gap-2 py-1 text-left text-sm">
                <Folder className="size-4 text-fg-3" />
                <span className="flex-1 truncate">{d.name}</span>
                <ChevronRight className="size-4 text-fg-3" />
              </button>
            </div>
          ))}
        {path && listing.data && listing.data.dirs.length === 0 && <p className="p-4 text-sm text-fg-3">No subfolders here.</p>}
      </div>
    </Modal>
  );
}
