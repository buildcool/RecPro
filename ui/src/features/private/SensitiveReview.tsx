import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { Check, CheckCircle2, Lock } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { Button, EmptyState } from '../../components/ui';
import { get, mediaUrl, post } from '../../lib/api';
import { num } from '../../lib/format';
import { usePrivateUi } from './PrivateLock';

type Item = { id: number; quick_v: number; kind: string; score: number; top: string | null };

const ANSWERS = [
  ['clear', 'Not sensitive'],
  ['romance', 'Romance'],
  ['suggestive', 'Suggestive'],
  ['nudity', 'Nudity'],
  ['sexual', 'Sexual'],
] as const;

/** "Please check" for private content: blurred, press and hold to peek, answer in batches. */
export function SensitiveReview() {
  const qc = useQueryClient();
  const ask = usePrivateUi((s) => s.ask);
  const { data } = useQuery({
    queryKey: ['review', 'sensitive'],
    queryFn: () => get<{ locked: boolean; items: Item[]; remaining: number }>('/api/review/sensitive?limit=24'),
  });
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [peek, setPeek] = useState<number | null>(null);

  if (!data) return null;
  if (data.locked)
    return (
      <EmptyState
        icon={<Lock className="size-6 text-private" />}
        title={`${num(data.remaining)} private items need a quick check`}
        body="Unlock Private to answer. They stay hidden and blurred until you do."
        actions={
          <Button variant="private" onClick={ask}>
            Unlock
          </Button>
        }
      />
    );
  if (data.items.length === 0)
    return <EmptyState icon={<CheckCircle2 className="size-6 text-ok" />} title="Nothing to check" body="Items RecPro isn't sure about appear here, blurred." />;

  const targets = sel.size ? [...sel] : data.items.map((i) => i.id);
  const answer = async (label: string) => {
    await post('/api/review/sensitive/answer', { media_ids: targets, label });
    toast.success(`${num(targets.length)} answered`);
    setSel(new Set());
    qc.invalidateQueries({ queryKey: ['review'] });
    qc.invalidateQueries({ queryKey: ['private'] });
  };

  return (
    <div>
      <p className="mb-3 text-[13px] text-fg-2">
        RecPro isn't sure about these {num(data.remaining)}. Tick some (or none for all), then choose what they are. Press and hold to peek.
      </p>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        {data.items.map((it) => {
          const on = sel.has(it.id);
          return (
            <div
              key={it.id}
              className={clsx('relative aspect-square cursor-pointer overflow-hidden rounded-xl border-2 bg-thumb', on ? 'border-private' : 'border-transparent')}
              onClick={() => setSel((s) => {
                const n = new Set(s);
                if (n.has(it.id)) n.delete(it.id);
                else n.add(it.id);
                return n;
              })}
              onPointerDown={(e) => {
                if (e.button === 0) {
                  const t = window.setTimeout(() => setPeek(it.id), 250);
                  (e.currentTarget as HTMLElement).dataset.t = String(t);
                }
              }}
              onPointerUp={(e) => {
                window.clearTimeout(Number((e.currentTarget as HTMLElement).dataset.t));
                setPeek(null);
              }}
              onPointerLeave={() => setPeek(null)}
            >
              <img src={mediaUrl(`media/thumb/${it.id}?v=${it.quick_v}`)} alt="" className={clsx('size-full object-cover transition', peek !== it.id && 'blur-private')} draggable={false} />
              <span className="absolute bottom-1.5 left-1.5 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">
                {it.top?.split('.')[1] ?? 'unsure'} · {Math.round(it.score * 100)}%
              </span>
              <span className={clsx('absolute right-2 top-2 flex size-6 items-center justify-center rounded-full border-2', on ? 'border-private bg-private text-white' : 'border-white bg-black/30 text-transparent')}>
                <Check className="size-3.5" strokeWidth={3} />
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-fg-2">{sel.size ? `${num(sel.size)} ticked:` : 'All shown:'}</span>
        {ANSWERS.map(([v, l]) => (
          <Button key={v} size="sm" variant={v === 'clear' ? 'secondary' : 'private'} onClick={() => void answer(v)}>
            {l}
          </Button>
        ))}
      </div>
    </div>
  );
}
