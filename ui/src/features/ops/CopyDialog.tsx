import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { AlertTriangle, CheckCircle2, FolderOpen, Info, Pause, Play, ShieldCheck, Undo2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button, Modal, Progress, Segmented, TextInput } from '../../components/ui';
import { ApiError, get, post } from '../../lib/api';
import { bridge } from '../../lib/bridge';
import { bytes, eta, num } from '../../lib/format';
import { useLive } from '../../lib/live';
import { type Op, useSettings } from '../../lib/queries';
import { useSelection } from '../../lib/selection';
import { useCopyFlow } from './CopyFlow';

type Plan = {
  count: number;
  bytes: number;
  free: number;
  enough_space: boolean;
  missing: number;
  same_place: number;
  conflicts: number;
  identical: number;
  dest: string;
  dest_exists: boolean;
  inside_source: boolean;
};

type Removal = 'bin' | 'recycle' | 'keep';

export function CopyDialog() {
  const flow = useCopyFlow();
  const { data: settings } = useSettings();
  const qc = useQueryClient();
  const [dest, setDest] = useState('');
  const [mode, setMode] = useState<'copy' | 'move'>('copy');
  const [structure, setStructure] = useState('keep');
  const [conflict, setConflict] = useState('rename');
  const [opId, setOpId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [removal, setRemoval] = useState<Removal>('bin');
  const [removing, setRemoving] = useState(false);
  const [removed, setRemoved] = useState<{ removed: number; skipped: { src: string; reason: string }[]; mode: Removal } | null>(null);
  const [showList, setShowList] = useState(false);

  // reset on open
  useEffect(() => {
    if (!flow.open) return;
    setOpId(null);
    setRemoved(null);
    setShowList(false);
    setMode(flow.mode);
    if (settings) {
      setStructure(flow.context?.personIds?.length ? 'person' : (settings['ops.structure_default'] as string));
      setConflict(settings['ops.conflict_default'] as string);
      setRemoval(settings['ops.removal_default'] as Removal);
    }
  }, [flow.open]); // eslint-disable-line react-hooks/exhaustive-deps

  const planReq = useMemo(
    () => ({ media_ids: flow.mediaIds, dest, structure, conflict, person_by_media: flow.context?.personByMedia }),
    [flow.mediaIds, dest, structure, conflict, flow.context],
  );
  const plan = useQuery({
    queryKey: ['ops', 'plan', planReq],
    queryFn: () => post<Plan>('/api/ops/plan', planReq),
    enabled: flow.open && !!dest && opId == null,
    retry: false,
  });

  const live = useLive((s) => (opId != null ? s.ops[opId] : undefined));
  const opQuery = useQuery({
    queryKey: ['ops', opId],
    queryFn: () => get<Op>(`/api/ops/${opId}`),
    enabled: opId != null,
    refetchInterval: (q) => (q.state.data && ['running', 'paused'].includes(q.state.data.status) ? 1500 : false),
  });
  const op = (live as unknown as Op | undefined) ?? opQuery.data;

  const failedItems = useQuery({
    queryKey: ['ops', opId, 'items', 'failed'],
    queryFn: () => get<{ src: string; error: string }[]>(`/api/ops/${opId}/items?state=failed&limit=50`),
    enabled: opId != null && op?.status === 'done' && (op?.counts?.failed ?? 0) > 0,
  });
  const removableItems = useQuery({
    queryKey: ['ops', opId, 'items', 'removable'],
    queryFn: async () => {
      const [v, i] = await Promise.all([
        get<{ src: string }[]>(`/api/ops/${opId}/items?state=verified&limit=300`),
        get<{ src: string }[]>(`/api/ops/${opId}/items?state=identical&limit=300`),
      ]);
      return [...v, ...i];
    },
    enabled: showList && opId != null,
  });

  const chooseDest = async () => {
    if (bridge) {
      const d = await bridge.pickFolder('Choose where to copy');
      if (d) setDest(d);
    }
  };

  const start = async () => {
    setStarting(true);
    try {
      const res = await post<Op>('/api/ops/copy', { ...planReq, mode, title: flow.context?.title });
      setOpId(res.id);
      useSelection.getState().clear();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const doRemove = async (m: Removal) => {
    if (opId == null) return;
    setRemoving(true);
    try {
      const r = await post<{ removed: number; skipped: { src: string; reason: string }[] }>(`/api/ops/${opId}/remove`, { mode: m });
      setRemoved({ ...r, mode: m });
      qc.invalidateQueries({ queryKey: ['ops'] });
      if (m === 'bin' && r.removed > 0) {
        toast.success(`Moved ${num(r.removed)} originals to the RecPro Bin`, {
          action: { label: 'Undo', onClick: () => void post(`/api/ops/${opId}/undo`).then(() => toast.success('Originals restored')) },
        });
      }
    } catch (e) {
      toast.error(String((e as Error).message));
    } finally {
      setRemoving(false);
    }
  };

  const running = op && (op.status === 'running' || op.status === 'paused');
  const done = op?.status === 'done';
  const verifiedCount = op ? (op.counts?.verified ?? 0) + (op.counts?.identical ?? 0) : 0;
  const copiedCount = verifiedCount + (op?.counts?.removed ?? 0);
  const failedCount = op?.counts?.failed ?? 0;
  const pct = op && op.bytes_total ? (op.bytes_done / op.bytes_total) * 100 : op && op.total ? (op.done / op.total) * 100 : 0;
  const rate = op?.rate ?? null;
  const left = rate && op ? (op.bytes_total - op.bytes_done) / rate : null;

  // ---------------- views ----------------
  let title: React.ReactNode = flow.mode === 'move' ? `Move ${num(flow.mediaIds.length)} items` : `Copy ${num(flow.mediaIds.length)} items`;
  let body: React.ReactNode;
  let footer: React.ReactNode;

  if (opId == null) {
    const p = plan.data;
    body = (
      <div className="space-y-5">
        <div>
          <div className="mb-1.5 text-[13px] font-medium">Destination</div>
          <div className="flex gap-2">
            {bridge ? (
              <button
                type="button"
                onClick={() => void chooseDest()}
                className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-left text-sm hover:border-accent"
              >
                <FolderOpen className="size-4 shrink-0 text-accent" />
                <span className={clsx('truncate', !dest && 'text-fg-3')}>{dest || 'Choose a folder…'}</span>
              </button>
            ) : (
              <TextInput placeholder={'D:\\Photos\\Rohit'} value={dest} onChange={(e) => setDest(e.target.value)} />
            )}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-1.5 text-[13px] font-medium">What happens to the originals</div>
            <Segmented
              size="sm"
              value={mode}
              onChange={setMode}
              options={[
                { value: 'copy', label: 'Ask me after' },
                { value: 'move', label: 'Move them' },
              ]}
            />
            <p className="mt-1.5 text-xs text-fg-3">
              {mode === 'copy' ? 'After every copy is verified, you decide.' : 'Each original goes to the RecPro Bin once its copy is verified. You can undo.'}
            </p>
          </div>
          <div>
            <div className="mb-1.5 text-[13px] font-medium">If a different file has the same name</div>
            <Segmented
              size="sm"
              value={conflict}
              onChange={setConflict}
              options={[
                { value: 'rename', label: 'Keep both' },
                { value: 'skip', label: 'Skip it' },
              ]}
            />
          </div>
        </div>
        <div>
          <div className="mb-1.5 text-[13px] font-medium">Folder layout at the destination</div>
          <Segmented
            size="sm"
            value={structure}
            onChange={setStructure}
            options={[
              { value: 'keep', label: 'Same folders' },
              { value: 'flat', label: 'All together' },
              { value: 'date', label: 'Year / month' },
              ...(flow.context?.personByMedia ? [{ value: 'person', label: 'By person' }] : []),
            ]}
          />
        </div>
        {dest && (
          <div className="rounded-xl bg-surface-2 p-4 text-[13px]">
            {plan.isLoading && <span className="text-fg-2">Checking the destination…</span>}
            {plan.error && <span className="text-bad">{(plan.error as Error).message}</span>}
            {p && (
              <div className="space-y-1.5">
                <div className="font-medium">
                  {num(p.count)} files · {bytes(p.bytes)} · {bytes(p.free)} free there
                </div>
                {!p.enough_space && (
                  <Note tone="bad">There isn't enough free space. Free up {bytes(p.bytes - p.free)} or choose another drive.</Note>
                )}
                {p.identical > 0 && <Note>{num(p.identical)} look already copied there. Identical files are checked and counted as copied.</Note>}
                {p.conflicts > 0 && (
                  <Note>
                    {num(p.conflicts)} have the same name as a different file there.{' '}
                    {conflict === 'rename' ? 'They’ll be saved as “name (1)”.' : 'They’ll be skipped.'}
                  </Note>
                )}
                {p.missing > 0 && <Note tone="warn">{num(p.missing)} originals are missing (their drive may be disconnected) and will be skipped.</Note>}
                {p.same_place > 0 && <Note>{num(p.same_place)} are already in that exact place and will be left alone.</Note>}
                {!p.dest_exists && <Note>The folder will be created.</Note>}
              </div>
            )}
          </div>
        )}
      </div>
    );
    footer = (
      <>
        <span className="mr-auto flex items-center gap-1.5 text-xs text-fg-3">
          <ShieldCheck className="size-4 text-ok" /> Every copy is checked byte for byte.
        </span>
        <Button variant="ghost" onClick={flow.close}>
          Cancel
        </Button>
        <Button variant="primary" loading={starting} disabled={!plan.data || !plan.data.enough_space || plan.data.count === 0} onClick={() => void start()}>
          {mode === 'move' ? 'Move' : 'Copy'} {plan.data ? num(plan.data.count) : ''} files
        </Button>
      </>
    );
  } else if (!op || running) {
    title = op?.status === 'paused' ? 'Paused' : mode === 'move' ? 'Moving…' : 'Copying…';
    body = (
      <div className="space-y-3">
        <Progress value={pct} />
        <div className="flex flex-wrap justify-between gap-2 text-[13px] text-fg-2">
          <span>
            {op ? `${num(op.done)} of ${num(op.total)} files · ${bytes(op.bytes_done)} of ${bytes(op.bytes_total)}` : 'Starting…'}
          </span>
          <span>{rate ? `${bytes(rate)}/s · ${eta(left)} left` : ''}</span>
        </div>
        {failedCount > 0 && <Note tone="warn">{num(failedCount)} files couldn't be copied so far. They'll be listed at the end.</Note>}
        <p className="text-xs text-fg-3">You can close this window. The copy continues, and you'll be notified when it's done. It also resumes if RecPro is closed.</p>
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={() => void post(`/api/ops/${opId}/cancel`)}>
          Cancel
        </Button>
        {op?.status === 'paused' ? (
          <Button icon={<Play className="size-4" />} onClick={() => void post(`/api/ops/${opId}/resume`)}>
            Resume
          </Button>
        ) : (
          <Button icon={<Pause className="size-4" />} onClick={() => void post(`/api/ops/${opId}/pause`)}>
            Pause
          </Button>
        )}
        <Button variant="primary" onClick={flow.close}>
          Run in background
        </Button>
      </>
    );
  } else if (done && !removed && op.removal == null) {
    title = (
      <span className="flex items-center gap-2">
        <CheckCircle2 className="size-5 text-ok" /> Copied and verified
      </span>
    );
    body = (
      <div className="space-y-4">
        <p className="text-sm">
          <strong className="font-semibold">{num(verifiedCount)} files</strong> are in <span className="font-medium">{op.dest}</span> and every copy matches its
          original byte for byte ({bytes(op.bytes_total)}).
        </p>
        {failedCount > 0 && (
          <div className="rounded-xl bg-warn-soft p-3 text-[13px] text-warn">
            <div className="mb-1 font-medium">{num(failedCount)} couldn't be copied. Their originals stay where they are.</div>
            <ul className="max-h-28 space-y-0.5 overflow-y-auto text-xs">
              {failedItems.data?.map((f) => (
                <li key={f.src} className="truncate" title={`${f.src}: ${f.error}`}>
                  {f.src.split(/[\\/]/).pop()}: {f.error}
                </li>
              ))}
            </ul>
            <Button size="xs" className="mt-2" onClick={() => void post(`/api/ops/${opId}/retry`)}>
              Try these again
            </Button>
          </div>
        )}
        {verifiedCount > 0 && (
          <div>
            <div className="mb-2 text-[15px] font-semibold">Remove the {num(verifiedCount)} originals?</div>
            <div className="space-y-2">
              {(
                [
                  ['bin', 'Move them to the RecPro Bin', 'Instant. Restore any time from History, exactly where they were.'],
                  ['recycle', 'Move them to the Windows Recycle Bin', 'Restore from the Recycle Bin. Network drives may not support it.'],
                  ['keep', 'Keep the originals', 'Nothing is removed; you now have two copies.'],
                ] as const
              ).map(([v, label, hint]) => (
                <label
                  key={v}
                  className={clsx(
                    'flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5',
                    removal === v ? 'border-accent bg-accent-soft/50' : 'border-line hover:bg-surface-2',
                  )}
                >
                  <input type="radio" name="removal" className="mt-1 accent-[var(--accent)]" checked={removal === v} onChange={() => setRemoval(v)} />
                  <span>
                    <span className="block text-sm font-medium">{label}</span>
                    <span className="block text-xs text-fg-2">{hint}</span>
                  </span>
                </label>
              ))}
            </div>
            <button type="button" className="mt-2 text-xs text-accent-text hover:underline" onClick={() => setShowList((v) => !v)}>
              {showList ? 'Hide the list' : `See the ${num(verifiedCount)} originals`}
            </button>
            {showList && (
              <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto rounded-lg bg-surface-2 p-2 text-xs text-fg-2">
                {removableItems.data?.map((i) => (
                  <li key={i.src} className="truncate" title={i.src}>
                    {i.src}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    );
    footer = (
      <>
        {bridge && (
          <Button variant="ghost" className="mr-auto" icon={<FolderOpen className="size-4" />} onClick={() => bridge!.openPath(op.dest)}>
            Open destination
          </Button>
        )}
        {removal === 'keep' ? (
          <Button variant="primary" loading={removing} onClick={() => void doRemove('keep').then(flow.close)}>
            Keep originals
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={() => void doRemove('keep').then(flow.close)}>
              Keep them
            </Button>
            <Button variant={removal === 'bin' ? 'primary' : 'danger'} loading={removing} disabled={verifiedCount === 0} onClick={() => void doRemove(removal)}>
              Remove {num(verifiedCount)} originals
            </Button>
          </>
        )}
      </>
    );
  } else {
    // finished: removed (or move mode), cancelled, failed, undone
    const r = removed;
    const movedToBin = r ? r.mode === 'bin' : op?.removal === 'bin';
    title =
      op?.status === 'cancelled' ? 'Copy cancelled' : op?.status === 'failed' ? "The copy couldn't finish" : (
        <span className="flex items-center gap-2">
          <CheckCircle2 className="size-5 text-ok" /> Done
        </span>
      );
    body = (
      <div className="space-y-3 text-sm">
        {op?.status === 'failed' && <Note tone="bad">{op.error ?? 'Something went wrong. Open History to resume.'}</Note>}
        {op?.status === 'cancelled' && <p>Copies already verified are kept. Nothing was removed.</p>}
        {(op?.status === 'done' || op?.status === 'undone') && (
          <p>
            {num(copiedCount)} files copied and verified to <span className="font-medium">{op.dest}</span>.{' '}
            {movedToBin
              ? `${num(r?.removed ?? op.counts?.removed ?? 0)} originals are in the RecPro Bin.`
              : r?.mode === 'recycle'
                ? `${num(r.removed)} originals are in the Windows Recycle Bin.`
                : 'The originals were kept.'}
          </p>
        )}
        {r && r.skipped.length > 0 && (
          <Note tone="warn">
            {num(r.skipped.length)} originals were kept: {r.skipped[0].reason}
          </Note>
        )}
      </div>
    );
    footer = (
      <>
        {movedToBin && opId != null && (
          <Button
            variant="ghost"
            className="mr-auto"
            icon={<Undo2 className="size-4" />}
            onClick={async () => {
              const u = await post<{ restored: number }>(`/api/ops/${opId}/undo`);
              toast.success(`Restored ${num(u.restored)} originals`);
              flow.close();
            }}
          >
            Undo
          </Button>
        )}
        {bridge && op?.dest && (
          <Button icon={<FolderOpen className="size-4" />} onClick={() => bridge!.openPath(op.dest)}>
            Open destination
          </Button>
        )}
        <Button variant="primary" onClick={flow.close}>
          Done
        </Button>
      </>
    );
  }

  return (
    <Modal open={flow.open} onOpenChange={(v) => !v && flow.close()} title={title} width="max-w-xl" footer={footer} dismissable={!starting}>
      {body}
    </Modal>
  );
}

function Note({ children, tone = 'info' }: { children: React.ReactNode; tone?: 'info' | 'warn' | 'bad' }) {
  const Icon = tone === 'info' ? Info : AlertTriangle;
  return (
    <div className={clsx('flex items-start gap-2 text-[13px]', tone === 'bad' ? 'text-bad' : tone === 'warn' ? 'text-warn' : 'text-fg-2')}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

/** Windows notification + toast when a copy finishes while its dialog is closed. */
export function useOpNotifications() {
  const ops = useLive((s) => s.ops);
  const [seen] = useState(() => new Map<number, string>());
  useEffect(() => {
    for (const op of Object.values(ops)) {
      const prev = seen.get(op.id);
      seen.set(op.id, op.status);
      if (prev && prev !== op.status && op.status === 'done' && !useCopyFlow.getState().open) {
        const msg = `${num(op.done)} files copied and verified`;
        toast.success(msg, { description: 'Open History and bin to decide about the originals.' });
        bridge?.notify('RecPro: copy finished', msg);
      }
    }
  }, [ops, seen]);
}
