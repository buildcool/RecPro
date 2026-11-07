import * as Tabs from '@radix-ui/react-tabs';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArchiveRestore, ArrowRightLeft, Copy, FolderOpen, Pause, Play, RotateCcw, Sparkles, Trash2, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { Badge, Button, Card, EmptyState, Modal, PageHeader, Progress } from '../components/ui';
import { get, post } from '../lib/api';
import { bridge } from '../lib/bridge';
import { bytes, dateTime, num, timeAgo } from '../lib/format';
import { useLive } from '../lib/live';
import { type Op, useOps } from '../lib/queries';

type BinGroup = { id: number; kind: string; title: string | null; dest: string; created_at: number; n: number; bytes: number };

const STATUS: Record<Op['status'], { label: string; tone: 'ok' | 'accent' | 'warn' | 'bad' | 'neutral' }> = {
  running: { label: 'Copying', tone: 'accent' },
  paused: { label: 'Paused', tone: 'warn' },
  done: { label: 'Verified', tone: 'ok' },
  failed: { label: 'Stopped', tone: 'bad' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  undone: { label: 'Undone', tone: 'neutral' },
};

export function HistoryPage() {
  const [tab, setTab] = useState('history');
  const { data: bin } = useQuery({ queryKey: ['bin'], queryFn: () => get<BinGroup[]>('/api/bin') });
  const binTotal = bin?.reduce((a, b) => a + b.bytes, 0) ?? 0;
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="History and bin" subtitle="Every copy, move and clean-up, and the files RecPro moved aside. Everything here can be undone." />
      <Tabs.Root value={tab} onValueChange={setTab} className="px-6 pb-12">
        <Tabs.List className="mb-4 inline-flex rounded-lg bg-surface-2 p-0.5" aria-label="History or bin">
          {[
            ['history', 'History'],
            ['bin', `RecPro Bin${bin?.length ? ` · ${bytes(binTotal)}` : ''}`],
          ].map(([v, l]) => (
            <Tabs.Trigger
              key={v}
              value={v}
              className="h-8 rounded-md px-3 text-[13px] font-medium text-fg-2 data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm"
            >
              {l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="history">
          <HistoryList />
        </Tabs.Content>
        <Tabs.Content value="bin">
          <BinList groups={bin ?? []} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

function HistoryList() {
  const { data: ops } = useOps();
  const liveOps = useLive((s) => s.ops);
  const qc = useQueryClient();
  const act = async (url: string, msg?: string) => {
    try {
      await post(url);
      if (msg) toast.success(msg);
      qc.invalidateQueries({ queryKey: ['ops'] });
      qc.invalidateQueries({ queryKey: ['bin'] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  if (ops && ops.length === 0)
    return <EmptyState icon={<Copy className="size-6" />} title="Nothing here yet" body="Copies, moves and clean-ups you make appear here, with undo." />;
  return (
    <div className="space-y-3">
      {ops?.map((o) => {
        const op = (liveOps[o.id] as unknown as Op | undefined) ?? o;
        const cleanup = op.kind === 'cleanup';
        const verified = (op.counts?.verified ?? 0) + (op.counts?.identical ?? 0);
        const removedN = op.counts?.removed ?? 0;
        const st: (typeof STATUS)['done'] =
          cleanup && op.status === 'done' ? { label: removedN ? 'In the bin' : 'Put back', tone: 'neutral' } : STATUS[op.status];
        const pct = op.bytes_total ? (op.bytes_done / op.bytes_total) * 100 : 0;
        return (
          <Card key={op.id} className="p-4">
            <div className="flex flex-wrap items-start gap-3">
              <div className="flex size-9 items-center justify-center rounded-xl bg-surface-2 text-fg-2">
                {cleanup ? <Sparkles className="size-4" /> : op.kind === 'move' ? <ArrowRightLeft className="size-4" /> : <Copy className="size-4" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{op.title || `${op.kind === 'move' ? 'Moved' : 'Copied'} ${num(op.total)} files`}</span>
                  <Badge tone={st.tone}>{st.label}</Badge>
                  {!cleanup && op.removal === 'bin' && removedN > 0 && <Badge tone="neutral">Originals in bin</Badge>}
                  {op.removal === 'recycle' && <Badge tone="neutral">Originals in Recycle Bin</Badge>}
                  {op.removal === 'keep' && <Badge tone="neutral">Originals kept</Badge>}
                </div>
                {cleanup ? (
                  <>
                    <div className="mt-0.5 text-[13px] text-fg-2">
                      {removedN
                        ? 'In the RecPro Bin. Undo puts them back where they were.'
                        : op.counts?.restored
                          ? 'Put back where they were.'
                          : 'Nothing was moved.'}
                    </div>
                    <div className="mt-1 text-xs text-fg-3">
                      {dateTime(op.created_at)} · {num(op.total)} {op.total === 1 ? 'file' : 'files'} · {bytes(op.bytes_total)}
                      {op.counts?.kept ? ` · ${num(op.counts.kept)} kept` : ''}
                      {op.counts?.restored ? ` · ${num(op.counts.restored)} put back` : ''}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="mt-0.5 truncate text-[13px] text-fg-2" title={op.dest}>
                      to {op.dest}
                    </div>
                    <div className="mt-1 text-xs text-fg-3">
                      {dateTime(op.created_at)} · {num(verified)} verified · {bytes(op.bytes_total)}
                      {op.counts?.failed ? ` · ${num(op.counts.failed)} failed` : ''}
                      {op.counts?.skipped ? ` · ${num(op.counts.skipped)} skipped` : ''}
                    </div>
                  </>
                )}
                {(op.status === 'running' || op.status === 'paused') && <Progress className="mt-2 max-w-md" value={pct} />}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {op.status === 'running' && (
                  <Button size="sm" icon={<Pause className="size-3.5" />} onClick={() => void act(`/api/ops/${op.id}/pause`)}>
                    Pause
                  </Button>
                )}
                {(op.status === 'paused' || op.status === 'failed') && (
                  <Button size="sm" variant="primary" icon={<Play className="size-3.5" />} onClick={() => void act(`/api/ops/${op.id}/resume`)}>
                    Resume
                  </Button>
                )}
                {op.status === 'done' && (op.counts?.failed ?? 0) > 0 && (
                  <Button size="sm" icon={<RotateCcw className="size-3.5" />} onClick={() => void act(`/api/ops/${op.id}/retry`)}>
                    Retry failed
                  </Button>
                )}
                {op.status === 'done' && op.removal == null && op.removable > 0 && (
                  <Button
                    size="sm"
                    icon={<Trash2 className="size-3.5" />}
                    onClick={() => void act(`/api/ops/${op.id}/remove`, `Moved ${num(op.removable)} originals to the RecPro Bin`)}
                  >
                    Move originals to bin
                  </Button>
                )}
                {bridge && !cleanup && (
                  <Button size="sm" variant="ghost" icon={<FolderOpen className="size-3.5" />} onClick={() => bridge!.openPath(op.dest)}>
                    Open
                  </Button>
                )}
                {(cleanup ? removedN > 0 : op.status === 'done' || removedN > 0) && (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Undo2 className="size-3.5" />}
                    onClick={() => void act(`/api/ops/${op.id}/undo`, cleanup ? 'Put back where they were' : removedN ? 'Originals restored' : 'Copies moved to the RecPro Bin')}
                  >
                    Undo
                  </Button>
                )}
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function BinList({ groups }: { groups: BinGroup[] }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<{ ids: number[] | null; n: number; bytes: number } | null>(null);
  const [ack, setAck] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['bin'] });
    qc.invalidateQueries({ queryKey: ['ops'] });
  };
  if (groups.length === 0)
    return (
      <EmptyState
        icon={<ArchiveRestore className="size-6" />}
        title="The bin is empty"
        body="When you remove originals after a verified copy, they wait here (on the same drive, using no extra space) until you restore them or empty the bin."
      />
    );
  const totalN = groups.reduce((a, g) => a + g.n, 0);
  const totalB = groups.reduce((a, g) => a + g.bytes, 0);
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl bg-surface-2 px-4 py-3 text-[13px]">
        <span className="flex-1 text-fg-2">
          {num(totalN)} files · {bytes(totalB)}. Files stay here until you restore them or empty the bin.
        </span>
        <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirm({ ids: null, n: totalN, bytes: totalB })}>
          Empty bin…
        </Button>
      </div>
      <div className="space-y-3">
        {groups.map((g) => (
          <Card key={g.id} className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{g.title || `From the ${g.kind} on ${dateTime(g.created_at)}`}</div>
              <div className="text-[13px] text-fg-2">
                {num(g.n)} files · {bytes(g.bytes)} · {timeAgo(g.created_at)}
              </div>
            </div>
            <Button
              size="sm"
              variant="primary"
              icon={<Undo2 className="size-3.5" />}
              onClick={async () => {
                const r = await post<{ restored: number; skipped: unknown[] }>('/api/bin/restore', { op_id: g.id });
                toast.success(`Restored ${num(r.restored)} files to where they were`);
                refresh();
              }}
            >
              Restore all
            </Button>
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirm({ ids: [g.id], n: g.n, bytes: g.bytes })}>
              Delete permanently…
            </Button>
          </Card>
        ))}
      </div>
      <Modal
        open={!!confirm}
        onOpenChange={(v) => {
          if (!v) {
            setConfirm(null);
            setAck(false);
          }
        }}
        title={`Permanently delete ${num(confirm?.n ?? 0)} files?`}
        description={`This frees ${bytes(confirm?.bytes ?? 0)}. These are originals whose copies were verified, but once deleted they can't be restored by RecPro or Windows.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={!ack}
              onClick={async () => {
                const c = confirm!;
                setConfirm(null);
                setAck(false);
                const r = await post<{ deleted: number; freed: number }>('/api/bin/empty', { op_ids: c.ids, confirm: true });
                toast.success(`Deleted ${num(r.deleted)} files, freed ${bytes(r.freed)}`);
                refresh();
              }}
            >
              Delete permanently
            </Button>
          </>
        }
      >
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--bad)]" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          I understand these files will be gone for good.
        </label>
      </Modal>
    </>
  );
}
