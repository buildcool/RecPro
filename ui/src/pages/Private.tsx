import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as Tabs from '@radix-ui/react-tabs';
import { Eye, EyeOff, KeyRound, Lock, LockOpen, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Badge, Button, Card, EmptyState, Modal, PageHeader, Switch } from '../components/ui';
import { Timeline } from '../features/grid/Timeline';
import { usePrivateState, usePrivateUi } from '../features/private/PrivateLock';
import { SensitiveReview } from '../features/private/SensitiveReview';
import { get, patch, post } from '../lib/api';
import { num } from '../lib/format';
import { useLive } from '../lib/live';

type LabelLite = { id: number; key: string; name: string };
const SECTIONS = [
  ['all', 'All'],
  ['romance', 'Romance'],
  ['suggestive', 'Suggestive'],
  ['nudity', 'Nudity'],
  ['sexual', 'Sexual'],
  ['review', 'Please check'],
] as const;

export function PrivatePage() {
  const { data: st } = usePrivateState();
  const live = useLive((s) => s.privateState);
  const ask = usePrivateUi((s) => s.ask);
  const qc = useQueryClient();
  const [tab, setTab] = useState<string>('all');
  const [resetOpen, setResetOpen] = useState(false);
  const labels = useQuery({ queryKey: ['labels', 'sensitive'], queryFn: () => get<LabelLite[]>('/api/labels?grp=sensitive'), retry: false });
  const unlocked = live?.unlocked ?? st?.unlocked ?? false;
  const s = st && live ? { ...st, ...live } : st;

  if (!s) return null;

  if (!s.configured || !unlocked) {
    return (
      <div className="h-full overflow-y-auto">
        <PageHeader title="Private" subtitle="Romance, suggestive, nudity and sexual photos and videos, kept apart and locked." />
        <div className="mx-auto max-w-xl px-6 pt-6">
          <Card className="flex flex-col items-center p-8 text-center">
            <div className="flex size-14 items-center justify-center rounded-2xl bg-private-soft text-private">
              {s.configured ? <Lock className="size-7" /> : <KeyRound className="size-7" />}
            </div>
            <h2 className="mt-4 text-[19px] font-semibold">{s.configured ? 'Private is locked' : 'Set up Private'}</h2>
            <p className="mt-2 text-sm text-fg-2">
              {s.counts.total > 0
                ? `${num(s.counts.total)} items are hidden from Photos, search, People and Find and move.`
                : 'When RecPro finds romance, suggestive or nudity content, it hides it here.'}{' '}
              {s.configured ? 'Unlock to see them.' : 'Choose a PIN or password to see them here.'}
            </p>
            <Button variant="private" size="lg" className="mt-5" icon={<LockOpen className="size-4" />} onClick={ask}>
              {s.configured ? 'Unlock' : 'Set up a PIN or password'}
            </Button>
            <ul className="mt-6 space-y-1.5 text-left text-[13px] text-fg-2">
              <li className="flex gap-2"><ShieldCheck className="size-4 shrink-0 text-ok" /> Private thumbnails are stored encrypted. Nothing readable is left in the data folder.</li>
              <li className="flex gap-2"><ShieldCheck className="size-4 shrink-0 text-ok" /> It locks again after {s.autoLockMinutes} minutes without activity, when Windows locks, or with Ctrl+L.</li>
              <li className="flex gap-2"><ShieldCheck className="size-4 shrink-0 text-ok" /> Your original files stay where they are; use Find and move to put them somewhere safer.</li>
            </ul>
            {s.configured && (
              <button type="button" className="mt-6 text-xs text-fg-3 hover:text-fg" onClick={() => setResetOpen(true)}>
                Forgot your PIN?
              </button>
            )}
          </Card>
        </div>
        <ResetDialog open={resetOpen} onClose={() => setResetOpen(false)} />
      </div>
    );
  }

  const labelId = (key: string) => labels.data?.find((l) => l.key === `sensitive.${key}`)?.id;
  const header = (
    <div className="px-6 pb-3 pt-5">
      <div className="flex flex-wrap items-center gap-3">
        <LockOpen className="size-5 text-private" />
        <h1 className="text-[22px] font-semibold tracking-tight">Private</h1>
        <Badge tone="private">Unlocked</Badge>
        <Countdown expiresAt={s.expiresAt ?? null} />
        <Button
          size="sm"
          className="ml-auto"
          icon={<Lock className="size-3.5" />}
          onClick={async () => {
            await post('/api/private/lock');
            qc.invalidateQueries({ queryKey: ['private'] });
          }}
        >
          Lock now · Ctrl+L
        </Button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-6 rounded-xl bg-surface p-3 text-[13px]">
        <label className="flex items-center gap-2">
          {s.blur ? <EyeOff className="size-4 text-fg-3" /> : <Eye className="size-4 text-fg-3" />}
          Blur
          <Switch tone="private" checked={s.blur} onChange={(v) => void setToggles(qc, { blur: v })} label="Blur" />
        </label>
        <label className="flex items-center gap-2">
          Show private items everywhere
          <Switch tone="private" checked={s.showEverywhere} onChange={(v) => void setToggles(qc, { showEverywhere: v })} label="Show private items everywhere" />
        </label>
        <span className="text-xs text-fg-3">
          {s.showEverywhere ? 'Private items now also appear in Photos, search, People and Find and move.' : 'Both reset when Private locks again.'}
          {s.blur ? ' Press and hold a photo to peek.' : ''}
        </span>
      </div>
      <Tabs.Root value={tab} onValueChange={setTab} className="mt-4">
        <Tabs.List className="inline-flex flex-wrap rounded-lg bg-surface-2 p-0.5" aria-label="Private sections">
          {SECTIONS.map(([v, l]) => {
            const n = v === 'all' ? s.counts.total : s.counts[v];
            return (
              <Tabs.Trigger
                key={v}
                value={v}
                className="flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium text-fg-2 data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm"
              >
                {l}
                {!!n && <span className="text-xs text-fg-3">{num(n)}</span>}
              </Tabs.Trigger>
            );
          })}
        </Tabs.List>
      </Tabs.Root>
    </div>
  );

  if (tab === 'review')
    return (
      <div className="h-full overflow-y-auto">
        {header}
        <div className="px-6 pb-10">
          <SensitiveReview />
        </div>
      </div>
    );

  const lid = tab === 'all' ? undefined : labelId(tab);
  return (
    <Timeline
      key={tab}
      scope={`private-${tab}`}
      filters={{ private_only: true, ...(lid ? { label_id: lid } : {}) }}
      header={header}
      empty={<EmptyState icon={<ShieldCheck className="size-6" />} title="Nothing here" body="Items RecPro finds for this section appear here." />}
    />
  );
}

async function setToggles(qc: ReturnType<typeof useQueryClient>, v: { blur?: boolean; showEverywhere?: boolean }) {
  try {
    const st = await patch('/api/private/toggles', v);
    useLive.setState({ privateState: st as never });
    qc.invalidateQueries();
  } catch (e) {
    toast.error((e as Error).message);
  }
}

function Countdown({ expiresAt }: { expiresAt: number | null }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);
  if (!expiresAt) return null;
  const left = Math.max(0, Math.round(expiresAt - now));
  return (
    <span className="text-[13px] text-fg-2">
      Locks in {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')} without activity
    </span>
  );
}

function ResetDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [ack, setAck] = useState(false);
  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Reset Private?"
      description="RecPro forgets the PIN, the private labels and the encrypted thumbnails, then checks your photos again. Nothing private is revealed, and your original files aren't touched."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={!ack}
            onClick={async () => {
              await post('/api/private/reset', { confirm: true });
              toast.success('Private was reset. Set up a new PIN when you are ready.');
              qc.invalidateQueries();
              onClose();
            }}
          >
            Reset Private
          </Button>
        </>
      }
    >
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 size-4" checked={ack} onChange={(e) => setAck(e.target.checked)} />
        I understand my answers about private items will be forgotten.
      </label>
    </Modal>
  );
}
