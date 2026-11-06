import { useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { CloudOff, ExternalLink, FolderOpen, FolderPlus, HardDriveDownload, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { Badge, Button, Card, EmptyState, IconButton, Modal, PageHeader, Switch, Tip } from '../components/ui';
import { addFoldersFlow } from '../features/library/addFolders';
import { del, patch, post } from '../lib/api';
import { bridge } from '../lib/bridge';
import { bytes, num, timeAgo } from '../lib/format';
import { useFolders } from '../lib/queries';
import type { Folder } from '../lib/types';

export function FoldersPage() {
  const { data: folders, isLoading } = useFolders();
  const qc = useQueryClient();
  const [removing, setRemoving] = useState<Folder | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ['folders'] });

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Folders"
        subtitle="RecPro looks for photos and videos in these folders. Your files stay where they are."
        actions={
          <>
            <Button icon={<RefreshCw className="size-4" />} onClick={() => post('/api/folders/rescan-all').then(() => toast('Checking all folders for changes'))}>
              Check for changes
            </Button>
            <Button variant="primary" icon={<FolderPlus className="size-4" />} onClick={() => void addFoldersFlow()}>
              Add folders
            </Button>
          </>
        }
      />
      <div className="space-y-3 px-6 pb-10">
        {!isLoading && folders?.length === 0 && (
          <EmptyState
            icon={<FolderOpen className="size-6" />}
            title="Add your first folder"
            body="Point RecPro at the folders where your photos and videos live: Pictures, a phone backup, an external drive. Nothing is moved or uploaded."
            actions={
              <Button variant="primary" icon={<FolderPlus className="size-4" />} onClick={() => void addFoldersFlow()}>
                Add folders
              </Button>
            }
          />
        )}
        {folders?.map((f) => (
          <Card key={f.id} className="p-4">
            <div className="flex flex-wrap items-start gap-3">
              <div className={clsx('flex size-10 items-center justify-center rounded-xl', f.online ? 'bg-accent-soft text-accent-text' : 'bg-surface-2 text-fg-3')}>
                {f.online ? <FolderOpen className="size-5" /> : <HardDriveDownload className="size-5" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-[15px] font-semibold" title={f.path}>
                    {f.path}
                  </span>
                  <StatusBadge f={f} />
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-fg-2">
                  <span>{num(f.photos)} photos</span>
                  <span>{num(f.videos)} videos</span>
                  <span>{bytes(f.bytes)}</span>
                  {f.last_scan_at && <span>Checked {timeAgo(f.last_scan_at)}</span>}
                </div>
                {f.skipped_cloud > 0 && (
                  <p className="mt-2 flex items-center gap-1.5 text-[13px] text-warn">
                    <CloudOff className="size-4" />
                    {num(f.skipped_cloud)} cloud-only files were skipped. Reading them would download them from the cloud. In OneDrive, choose
                    “Always keep on this device” to include them.
                  </p>
                )}
                {!f.online && (
                  <p className="mt-2 text-[13px] text-fg-2">This drive isn't connected. Thumbnails and everything RecPro learned are kept; reconnect it to open originals.</p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <IconButton label="Check this folder for changes" onClick={() => post(`/api/folders/${f.id}/rescan`).then(refresh)}>
                  <RefreshCw className="size-4" />
                </IconButton>
                {bridge && (
                  <IconButton label="Open in File Explorer" onClick={() => bridge!.openPath(f.path)}>
                    <ExternalLink className="size-4" />
                  </IconButton>
                )}
                <IconButton label="Remove from RecPro" onClick={() => setRemoving(f)}>
                  <Trash2 className="size-4" />
                </IconButton>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-6 border-t border-line pt-3 text-[13px]">
              <label className="flex items-center gap-2 text-fg-2">
                <Switch checked={f.watch} onChange={(v) => patch(`/api/folders/${f.id}`, { watch: v }).then(refresh)} label="Watch for new photos" />
                Watch for new photos
              </label>
              <label className="flex items-center gap-2 text-fg-2">
                <Switch checked={f.recursive} onChange={(v) => patch(`/api/folders/${f.id}`, { recursive: v }).then(refresh)} label="Include subfolders" />
                Include subfolders
              </label>
            </div>
          </Card>
        ))}
      </div>
      <Modal
        open={!!removing}
        onOpenChange={(v) => !v && setRemoving(null)}
        title="Remove this folder from RecPro?"
        description={
          <>
            <span className="font-medium text-fg">{removing?.path}</span> stops being part of your library. Its files stay exactly where they are. What RecPro
            learned about them (faces, categories) is forgotten.
          </>
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              Keep it
            </Button>
            <Button
              variant="danger"
              onClick={async () => {
                const f = removing!;
                setRemoving(null);
                await del(`/api/folders/${f.id}`);
                refresh();
                toast.success('Folder removed from RecPro', { description: 'No files were deleted.' });
              }}
            >
              Remove from RecPro
            </Button>
          </>
        }
      />
    </div>
  );
}

function StatusBadge({ f }: { f: Folder }) {
  if (!f.online || f.status === 'offline') return <Badge>Disconnected</Badge>;
  if (f.status === 'scanning')
    return (
      <Tip label="Looking for new, changed and removed files">
        <span>
          <Badge tone="accent">Checking…</Badge>
        </span>
      </Tip>
    );
  if (f.status === 'pending') return <Badge tone="accent">Waiting</Badge>;
  return <Badge tone="ok">Up to date</Badge>;
}
