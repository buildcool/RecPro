import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { Check, Copy, GalleryHorizontal, Layers, Maximize2, MessageCircle, MoonStar, ScanEye, Trash2 } from 'lucide-react';
import { type ReactNode, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button, EmptyState, PageHeader } from '../components/ui';
import { useViewer } from '../features/viewer/viewerStore';
import { get, mediaUrl, post } from '../lib/api';
import { bytes, num } from '../lib/format';
import { type CleanupKind, useCleanupSummary } from '../lib/queries';
import type { MediaItem } from '../lib/types';

type CleanItem = MediaItem & { path: string; name: string; size: number; folder: string; keep?: boolean; greeting?: boolean };
type BinResult = { op_id: number; removed: number; skipped: { src: string; reason: string }[] };

const KINDS: { key: CleanupKind; title: string; body: string; icon: typeof Copy; groups: boolean }[] = [
  { key: 'exact', title: 'Exact duplicates', body: 'The very same file saved more than once. One copy stays.', icon: Copy, groups: true },
  {
    key: 'copies',
    title: 'Copies',
    body: 'The same photo saved again, smaller or recompressed (WhatsApp, edits, downloads). The original stays: the camera file, the largest, the sharpest.',
    icon: Layers,
    groups: true,
  },
  { key: 'bursts', title: 'Similar shots', body: 'Several shots of the same moment, seconds apart. The sharpest, best-exposed one stays.', icon: GalleryHorizontal, groups: true },
  { key: 'dark', title: 'Too dark', body: 'Almost black, with nothing bright in them. Night shots with lights in them aren’t here.', icon: MoonStar, groups: false },
  { key: 'blurry', title: 'Blurry or by accident', body: 'Badly out of focus, shaken, or taken by accident.', icon: ScanEye, groups: false },
  { key: 'forwards', title: 'WhatsApp forwards', body: 'Images that came in through WhatsApp. Greetings and memes come first.', icon: MessageCircle, groups: false },
];

/** Members in id order, so a group keeps its identity when its order or ranking changes. */
const groupKey = (g: CleanItem[]) =>
  g
    .map((x) => x.id)
    .sort((a, b) => a - b)
    .join('-');

export function CleanupPage() {
  const [kind, setKind] = useState<CleanupKind>('exact');
  const { data: s } = useCleanupSummary();
  const total = s?.total?.bytes ?? 0;
  const active = KINDS.find((k) => k.key === kind)!;

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Clean up"
        subtitle={`Free up space safely: whatever you remove goes to the RecPro Bin, and Undo puts it back.${total ? ` Up to ${bytes(total)} to free.` : ''}`}
      />
      <div className="px-6 pb-12">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-2" role="tablist" aria-label="Kind of cleanup">
          {KINDS.map((k) => {
            const v = s?.[k.key];
            const n = k.groups ? v?.groups : v?.files;
            const on = kind === k.key;
            return (
              <button
                key={k.key}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => setKind(k.key)}
                className={clsx(
                  'flex items-start gap-3 rounded-xl border p-3 text-left transition-colors',
                  on ? 'border-accent bg-accent-soft/50' : 'border-line bg-surface hover:bg-surface-2',
                )}
              >
                <k.icon className={clsx('mt-0.5 size-5 shrink-0', on ? 'text-accent' : 'text-fg-3')} />
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold">{k.title}</div>
                  <div className="text-xs text-fg-2">
                    {v == null ? '…' : n ? `${num(n)} ${k.groups ? (n === 1 ? 'group' : 'groups') : n === 1 ? 'photo' : 'photos'} · ${bytes(v.bytes)}` : 'Nothing'}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
        <p className="mb-4 mt-5 max-w-3xl text-sm text-fg-2">{active.body}</p>
        {active.groups ? <Groups key={kind} kind={kind} title={active.title} /> : <Flat key={kind} kind={kind} title={active.title} />}
      </div>
    </div>
  );
}

function useAfterBin() {
  const qc = useQueryClient();
  return (res: BinResult) => {
    const refresh = () => {
      for (const k of ['cleanup', 'timeline', 'media', 'stats', 'ops', 'bin']) qc.invalidateQueries({ queryKey: [k] });
    };
    refresh();
    if (res.removed) {
      toast.success(`Moved ${num(res.removed)} ${res.removed === 1 ? 'file' : 'files'} to the RecPro Bin`, {
        duration: 10_000,
        action: {
          label: 'Undo',
          onClick: () =>
            void post(`/api/ops/${res.op_id}/undo`)
              .then(() => toast.success('Put back where they were'))
              .catch((e: Error) => toast.error(e.message))
              .finally(refresh),
        },
      });
    }
    if (res.skipped.length) toast.warning(`${num(res.skipped.length)} kept: ${res.skipped[0].reason}`);
  };
}

/** A photo to choose: click toggles it, the corner button opens it full size. */
function Tile({ it, on, badge, dim, label, onToggle, onOpen }: { it: CleanItem; on: boolean; badge?: ReactNode; dim?: boolean; label: string; onToggle: () => void; onOpen: () => void }) {
  return (
    <div className="group relative min-w-0">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={on}
        aria-label={label}
        className={clsx(
          'relative block aspect-square w-full overflow-hidden rounded-lg bg-thumb outline-offset-2 transition-opacity',
          on && 'outline outline-2 outline-accent',
          dim && 'opacity-60 hover:opacity-100',
        )}
      >
        <img src={mediaUrl(`media/thumb/${it.id}?v=${it.v}`)} alt="" loading="lazy" className={clsx('size-full object-cover', it.priv && 'blur-private')} />
        {badge}
      </button>
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Look closer at ${it.name}`}
        title="Look closer"
        className="absolute right-1.5 top-1.5 rounded-md bg-black/60 p-1 text-white opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Maximize2 className="size-3.5" />
      </button>
      <div className="mt-1 truncate text-[11px] text-fg-2" title={it.path}>
        {it.name}
      </div>
      <div className="truncate text-[11px] text-fg-3">
        {bytes(it.size)}
        {it.w ? ` · ${it.w} × ${it.h}` : ''}
      </div>
    </div>
  );
}

function Groups({ kind, title }: { kind: CleanupKind; title: string }) {
  const [limit, setLimit] = useState(60);
  const { data, isLoading } = useQuery({
    queryKey: ['cleanup', kind, limit],
    queryFn: () => get<{ total: number; groups: CleanItem[][] }>(`/api/cleanup/${kind}?limit=${limit}`),
    placeholderData: (prev) => prev,
  });
  const [choice, setChoice] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const after = useAfterBin();
  const groups = useMemo(() => data?.groups ?? [], [data]);
  // the one that stays: your pick if it's still in the group, else the best one RecPro found
  const kept = (g: CleanItem[]) => {
    const pick = choice[groupKey(g)];
    return g.some((x) => x.id === pick) ? pick : (g.find((x) => x.keep) ?? g[0]).id;
  };
  const extras = (gs: CleanItem[][]) => gs.flatMap((g) => g.filter((x) => x.id !== kept(g)).map((x) => [x, kept(g)] as const));

  const remove = async (gs: CleanItem[][], key: string) => {
    const pairs = extras(gs);
    if (!pairs.length) return;
    setBusy(key);
    try {
      const stays = Object.fromEntries(pairs.map(([x, k]) => [x.id, k]));
      const res = await post<BinResult>('/api/cleanup/bin', {
        media_ids: pairs.map(([x]) => x.id),
        title: `Clean up: ${title}`,
        // exact duplicates are removed only if their content matches the one kept, byte for byte
        ...(kind === 'exact' ? { same_as: stays } : { keeps: stays }),
      });
      after(res);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (isLoading) return null;
  if (!groups.length) return <EmptyState icon={<Check className="size-6" />} title="Nothing to clean up here" body="RecPro keeps looking as new photos arrive." />;
  const all = extras(groups);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-fg-2">
          {num(data!.total)} {data!.total === 1 ? 'group' : 'groups'}
          {data!.total > groups.length ? ` (showing ${num(groups.length)})` : ''} · the photo marked Keep stays; click another to keep that one instead
        </span>
        <Button
          variant="primary"
          size="sm"
          className="ml-auto"
          loading={busy === 'all'}
          disabled={busy != null}
          icon={<Trash2 className="size-4" />}
          onClick={() => void remove(groups, 'all')}
        >
          Keep one of each, move {num(all.length)} to Bin ({bytes(all.reduce((a, [x]) => a + x.size, 0))})
        </Button>
      </div>
      <div className="space-y-3">
        {groups.map((g) => {
          const key = groupKey(g);
          const k = kept(g);
          const keeper = g.find((x) => x.id === k)!;
          const rest = g.filter((x) => x.id !== k);
          return (
            <div key={key} role="group" className="rounded-xl border border-line bg-surface p-3" aria-label={`${g.length} photos, keeps ${keeper.name}`}>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-2">
                {g.map((x, i) => (
                  <Tile
                    key={x.id}
                    it={x}
                    on={x.id === k}
                    dim={x.id !== k}
                    label={x.id === k ? `${x.name}: stays` : `${x.name}: goes to the Bin. Click to keep this one instead`}
                    badge={
                      x.id === k ? (
                        <span className="absolute left-1.5 top-1.5 rounded-md bg-accent px-1.5 py-0.5 text-[10px] font-semibold text-accent-fg">Keep</span>
                      ) : undefined
                    }
                    onToggle={() => setChoice((s) => ({ ...s, [key]: x.id }))}
                    onOpen={() => useViewer.getState().show(g.map((y) => y.id), i)}
                  />
                ))}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-fg-3">
                <span className="min-w-0 flex-1 truncate" title={keeper.path}>
                  Keeps the one in {keeper.folder}
                </span>
                <Button size="sm" loading={busy === key} disabled={busy != null} onClick={() => void remove([g], key)}>
                  Move {num(rest.length)} to Bin ({bytes(rest.reduce((a, x) => a + x.size, 0))})
                </Button>
              </div>
            </div>
          );
        })}
      </div>
      {data!.total > groups.length && limit < 200 && (
        <div className="mt-4 flex justify-center">
          <Button onClick={() => setLimit((l) => Math.min(200, l + 60))}>Show more</Button>
        </div>
      )}
    </div>
  );
}

function Flat({ kind, title }: { kind: CleanupKind; title: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['cleanup', kind], queryFn: () => get<{ total: number; items: CleanItem[] }>(`/api/cleanup/${kind}?limit=200`) });
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const after = useAfterBin();
  const items = data?.items ?? [];
  if (isLoading) return null;
  if (!items.length) return <EmptyState icon={<Check className="size-6" />} title="Nothing to clean up here" body="RecPro keeps looking as new photos arrive." />;
  // only what's on screen can be removed: a choice that disappeared from the list is dropped
  const chosen = items.filter((x) => sel.has(x.id));
  const everything = chosen.length === items.length;
  const remove = async () => {
    setBusy(true);
    try {
      const res = await post<BinResult>('/api/cleanup/bin', { media_ids: chosen.map((x) => x.id), title: `Clean up: ${title}` });
      setSel(new Set());
      after(res);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const toggle = (id: number) =>
    setSel((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-fg-2">
          {num(data!.total)} {data!.total === 1 ? 'photo' : 'photos'}
          {data!.total > items.length ? ` (showing ${num(items.length)})` : ''} · nothing is chosen until you click it
        </span>
        <Button size="sm" onClick={() => setSel(everything ? new Set() : new Set(items.map((x) => x.id)))}>
          {everything ? 'Choose none' : 'Choose all'}
        </Button>
        <Button variant="primary" size="sm" className="ml-auto" disabled={!chosen.length} loading={busy} icon={<Trash2 className="size-4" />} onClick={() => void remove()}>
          Move {num(chosen.length)} to Bin{chosen.length ? ` (${bytes(chosen.reduce((a, x) => a + x.size, 0))})` : ''}
        </Button>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-2">
        {items.map((x, i) => {
          const on = sel.has(x.id);
          return (
            <Tile
              key={x.id}
              it={x}
              on={on}
              label={on ? `${x.name}: chosen for the Bin` : x.name}
              badge={
                <>
                  {on && (
                    <span className="absolute left-1.5 top-1.5 flex size-5 items-center justify-center rounded-full bg-accent text-accent-fg">
                      <Check className="size-3.5" strokeWidth={3} />
                    </span>
                  )}
                  {x.greeting && <span className="absolute bottom-1.5 left-1.5 rounded bg-black/60 px-1 text-[10px] text-white">Greeting or meme</span>}
                </>
              }
              onToggle={() => toggle(x.id)}
              onOpen={() => useViewer.getState().show(items.map((y) => y.id), i)}
            />
          );
        })}
      </div>
    </div>
  );
}
