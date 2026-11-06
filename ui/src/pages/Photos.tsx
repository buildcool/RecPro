import { FolderPlus, Images } from 'lucide-react';
import { useState } from 'react';
import { Button, EmptyState, PageHeader, Segmented } from '../components/ui';
import { addFoldersFlow } from '../features/library/addFolders';
import { Timeline } from '../features/grid/Timeline';
import { useZoom } from '../features/grid/zoom';
import { num } from '../lib/format';
import { useStats } from '../lib/queries';

export function PhotosPage() {
  const [kind, setKind] = useState<'all' | 'image' | 'video'>('all');
  const { zoom, setZoom } = useZoom();
  const { data: stats } = useStats();
  const total = stats ? stats.photos + stats.videos : undefined;

  return (
    <Timeline
      scope="photos"
      filters={kind === 'all' ? {} : { kind }}
      header={
        <PageHeader
          title="Photos"
          subtitle={total != null ? `${num(stats!.photos)} photos and ${num(stats!.videos)} videos` : undefined}
          actions={
            <>
              <Segmented
                size="sm"
                value={kind}
                onChange={setKind}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'image', label: 'Photos' },
                  { value: 'video', label: 'Videos' },
                ]}
              />
              <Segmented
                size="sm"
                value={zoom}
                onChange={setZoom}
                options={[
                  { value: 'small', label: 'S', hint: 'Small thumbnails' },
                  { value: 'medium', label: 'M', hint: 'Medium thumbnails' },
                  { value: 'large', label: 'L', hint: 'Large thumbnails' },
                ]}
              />
            </>
          }
        />
      }
      empty={
        <EmptyState
          icon={<Images className="size-6" />}
          title={kind === 'video' ? 'No videos yet' : 'No photos yet'}
          body="Add the folders where your photos and videos are. They appear here within seconds."
          actions={
            <Button variant="primary" icon={<FolderPlus className="size-4" />} onClick={() => void addFoldersFlow()}>
              Add folders
            </Button>
          }
        />
      }
    />
  );
}
