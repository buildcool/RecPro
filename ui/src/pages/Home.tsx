import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Copy, FolderPlus, ImagePlus, MessageCircleQuestion, Undo2, UserRound, Wand2 } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Badge, Button, Card, Progress, SectionTitle } from '../components/ui';
import { addFoldersFlow } from '../features/library/addFolders';
import { ModelSetupCard } from '../features/models/ModelSetup';
import { get, mediaUrl, post } from '../lib/api';
import { bytes, eta, num, timeAgo } from '../lib/format';
import { useLive } from '../lib/live';
import { useFolders, useOps, useStats } from '../lib/queries';

type PersonLite = { id: number; name: string | null; count: number; cover_face_id: number | null };

export function HomePage() {
  const { data: stats } = useStats();
  const status = useLive((s) => s.status);
  const { data: folders } = useFolders();
  const { data: ops } = useOps();
  const nav = useNavigate();
  const people = useQuery({ queryKey: ['people', 'top'], queryFn: () => get<PersonLite[]>('/api/people?named=1&limit=8'), retry: false });

  const stages = status ? Object.entries(status.stages).filter(([, s]) => s.total > 0) : [];
  const busy = stages.some(([, s]) => s.done < s.total);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 px-6 pb-12 pt-6">
        {/* Hero: find someone */}
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-6 p-6">
            <div className="min-w-0 flex-1">
              <h1 className="text-[22px] font-semibold tracking-tight">Find someone</h1>
              <p className="mt-1 max-w-xl text-sm text-fg-2">
                Pick a person or drop a photo of them. RecPro finds every photo and video they're in across your folders, asks you when it isn't sure, then
                copies them wherever you want.
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button variant="primary" size="lg" icon={<Wand2 className="size-[18px]" />} onClick={() => nav('/find')}>
                  Find and move
                </Button>
                <Button size="lg" icon={<ImagePlus className="size-[18px]" />} onClick={() => nav('/find?by=photo')}>
                  Use a photo
                </Button>
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              {(people.data ?? []).slice(0, 6).map((p) => (
                <Link key={p.id} to={`/find?person=${p.id}`} className="group flex w-16 flex-col items-center gap-1.5">
                  {p.cover_face_id ? (
                    <img src={mediaUrl(`media/face/${p.cover_face_id}`)} alt="" className="size-14 rounded-full object-cover ring-2 ring-transparent transition group-hover:ring-accent" />
                  ) : (
                    <span className="flex size-14 items-center justify-center rounded-full bg-surface-2">
                      <UserRound className="size-6 text-fg-3" />
                    </span>
                  )}
                  <span className="w-full truncate text-center text-xs text-fg-2">{p.name}</span>
                </Link>
              ))}
              {(people.data?.length ?? 0) === 0 && (
                <div className="max-w-[220px] rounded-xl bg-surface-2 p-3 text-xs text-fg-2">
                  People you name appear here. Faces are grouped automatically after your photos are analyzed.
                </div>
              )}
            </div>
          </div>
        </Card>

        <ModelSetupCard need="faces" />

        {/* Numbers */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Photos" value={num(stats?.photos)} />
          <Metric label="Videos" value={num(stats?.videos)} />
          <Metric label="People" value={num(stats?.named_people)} hint={stats && stats.people > stats.named_people ? `${num(stats.people - stats.named_people)} unnamed` : undefined} />
          <Metric
            label="Needs your answer"
            value={num(stats?.review)}
            tone={stats?.review ? 'warn' : undefined}
            action={stats?.review ? () => nav('/review') : undefined}
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          {/* Indexing */}
          <Card className="p-5">
            <SectionTitle right={busy ? <Badge tone="accent">Working</Badge> : <Badge tone="ok">Up to date</Badge>}>Analysis on this PC</SectionTitle>
            {stages.length === 0 && <p className="text-sm text-fg-2">Add a folder to start. Everything is analyzed on this computer.</p>}
            <div className="space-y-4">
              {stages.map(([key, s]) => (
                <div key={key}>
                  <div className="mb-1.5 flex items-baseline justify-between text-[13px]">
                    <span className="font-medium">{s.label}</span>
                    <span className="text-fg-2">
                      {num(s.done)} of {num(s.total)}
                      {s.rate ? ` · ${s.rate.toFixed(0)}/s` : ''}
                    </span>
                  </div>
                  <Progress value={s.total ? (s.done / s.total) * 100 : 0} tone={s.done >= s.total ? 'ok' : 'accent'} />
                </div>
              ))}
            </div>
            {busy && status?.etaSec ? <p className="mt-4 text-xs text-fg-3">Time left: {eta(status.etaSec)}. You can keep using RecPro meanwhile.</p> : null}
          </Card>

          {/* Folders */}
          <Card className="p-5">
            <SectionTitle
              right={
                <Button size="sm" variant="ghost" icon={<FolderPlus className="size-4" />} onClick={() => void addFoldersFlow()}>
                  Add
                </Button>
              }
            >
              Folders
            </SectionTitle>
            <div className="space-y-2">
              {(folders ?? []).slice(0, 5).map((f) => (
                <Link key={f.id} to="/folders" className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-[13px] hover:bg-surface-2">
                  <span className="truncate" title={f.path}>
                    {f.path}
                  </span>
                  <span className="shrink-0 text-fg-3">{num(f.photos + f.videos)}</span>
                </Link>
              ))}
              {folders?.length === 0 && <p className="text-sm text-fg-2">No folders yet.</p>}
            </div>
            {stats && <p className="mt-3 text-xs text-fg-3">{bytes(stats.bytes)} of photos and videos in your library</p>}
          </Card>
        </div>

        {/* Recent operations */}
        {(ops?.length ?? 0) > 0 && (
          <Card className="p-5">
            <SectionTitle
              right={
                <Link to="/history" className="flex items-center gap-1 text-[13px] text-accent-text hover:underline">
                  All history <ArrowRight className="size-3.5" />
                </Link>
              }
            >
              Recent copies and moves
            </SectionTitle>
            <div className="divide-y divide-line">
              {ops!.slice(0, 4).map((op) => (
                <div key={op.id} className="flex items-center gap-3 py-2.5 text-[13px]">
                  <Copy className="size-4 text-fg-3" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{op.title || `${op.kind === 'move' ? 'Moved' : 'Copied'} ${num(op.total)} files`}</div>
                    <div className="truncate text-fg-3">
                      to {op.dest} · {timeAgo(op.created_at)}
                      {op.removal === 'bin' ? ' · originals in the bin' : ''}
                    </div>
                  </div>
                  <Badge tone={op.status === 'done' ? 'ok' : op.status === 'failed' ? 'bad' : op.status === 'undone' ? 'neutral' : 'accent'}>{op.status}</Badge>
                  {op.status === 'done' && (
                    <Button
                      size="xs"
                      variant="ghost"
                      icon={<Undo2 className="size-3.5" />}
                      onClick={async () => {
                        const r = await post<{ restored: number; copies_binned: number }>(`/api/ops/${op.id}/undo`);
                        toast.success(r.restored ? `Restored ${num(r.restored)} originals` : `Moved ${num(r.copies_binned)} copies to the bin`);
                      }}
                    >
                      Undo
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {stats && stats.photos + stats.videos === 0 && (
          <Card className="flex flex-wrap items-center gap-4 p-5">
            <MessageCircleQuestion className="size-6 text-accent" />
            <div className="min-w-0 flex-1 text-sm text-fg-2">Start by adding the folders where your photos and videos are. RecPro never moves or uploads anything on its own.</div>
            <Button variant="primary" icon={<FolderPlus className="size-4" />} onClick={() => void addFoldersFlow()}>
              Add folders
            </Button>
          </Card>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value, hint, tone, action }: { label: string; value: string; hint?: string; tone?: 'warn'; action?: () => void }) {
  const inner = (
    <>
      <div className="text-[13px] text-fg-2">{label}</div>
      <div className={`mt-1 text-[24px] font-semibold tracking-tight ${tone === 'warn' ? 'text-warn' : ''}`}>{value}</div>
      {hint && <div className="text-xs text-fg-3">{hint}</div>}
    </>
  );
  return action ? (
    <button type="button" onClick={action} className="rounded-2xl bg-surface-2 p-4 text-left transition-colors hover:bg-surface-3">
      {inner}
    </button>
  ) : (
    <div className="rounded-2xl bg-surface-2 p-4">{inner}</div>
  );
}
