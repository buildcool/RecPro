import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { ArrowLeft, Check, Sparkles, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { toast } from 'sonner';
import { Badge, Button, Card } from '../components/ui';
import { Timeline } from '../features/grid/Timeline';
import { useViewer } from '../features/viewer/viewerStore';
import { del, get, mediaUrl, post } from '../lib/api';
import { num } from '../lib/format';
import type { MediaItem } from '../lib/types';

type LabelInfo = { id: number; key: string; name: string; grp: string; prompts: string[]; builtin: number; count: number; maybe: number; answers: number };

export function LabelPage() {
  const { id } = useParams();
  const lid = Number(id);
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: l } = useQuery({ queryKey: ['labels', 'detail', lid], queryFn: () => get<LabelInfo>(`/api/labels/${lid}`) });
  const maybe = useQuery({
    queryKey: ['labels', 'maybe', lid],
    queryFn: () => get<(MediaItem & { score: number })[]>(`/api/labels/${lid}/maybe?limit=24`),
    enabled: !!l && l.maybe > 0,
  });
  const [yes, setYes] = useState<Set<number>>(new Set());

  const header = l && (
    <div className="px-6 pb-3 pt-5">
      <Link to="/explore" className="mb-3 inline-flex items-center gap-1 text-[13px] text-fg-2 hover:text-fg">
        <ArrowLeft className="size-4" /> Explore
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[24px] font-semibold tracking-tight">{l.name}</h1>
        {!l.builtin && <Badge tone="accent">Your category</Badge>}
        <span className="text-sm text-fg-2">
          {num(l.count)} items{l.maybe ? ` · ${num(l.maybe)} maybe` : ''}
        </span>
        {!l.builtin && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            icon={<Trash2 className="size-3.5" />}
            onClick={async () => {
              await del(`/api/labels/${lid}`);
              toast.success(`Deleted ${l.name}`);
              qc.invalidateQueries({ queryKey: ['explore'] });
              nav('/explore');
            }}
          >
            Delete category
          </Button>
        )}
      </div>
      {!l.builtin && l.prompts.length > 0 && <p className="mt-1 text-[13px] text-fg-3">Looks for: {l.prompts.join(' · ')}</p>}
      {l.answers >= 16 && (
        <p className="mt-1 flex items-center gap-1.5 text-[13px] text-ok">
          <Sparkles className="size-4" /> Learned from your {num(l.answers)} answers
        </p>
      )}
      {(maybe.data?.length ?? 0) > 0 && (
        <Card className="mt-4 p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="text-[15px] font-semibold">Maybe {l.name.toLowerCase()}?</h2>
            <span className="text-[13px] text-fg-2">Tick the ones that are. Each answer teaches this category.</span>
            <Button
              size="sm"
              variant="primary"
              className="ml-auto"
              icon={<Check className="size-3.5" />}
              onClick={async () => {
                const items = maybe.data!;
                const r = await post<{ learning: number }>(`/api/labels/${lid}/answer`, {
                  yes: items.filter((i) => yes.has(i.id)).map((i) => i.id),
                  no: items.filter((i) => !yes.has(i.id)).map((i) => i.id),
                });
                toast.success(r.learning ? 'Saved. RecPro is learning this category from your answers.' : 'Saved');
                setYes(new Set());
                qc.invalidateQueries({ queryKey: ['labels'] });
                qc.invalidateQueries({ queryKey: ['timeline'] });
                qc.invalidateQueries({ queryKey: ['media'] });
              }}
            >
              Save ({num(yes.size)} yes, {num((maybe.data?.length ?? 0) - yes.size)} no)
            </Button>
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2">
            {maybe.data!.map((it) => {
              const on = yes.has(it.id);
              return (
                <div
                  key={it.id}
                  role="checkbox"
                  aria-checked={on}
                  tabIndex={0}
                  onClick={() => setYes((s) => {
                    const n = new Set(s);
                    if (n.has(it.id)) n.delete(it.id);
                    else n.add(it.id);
                    return n;
                  })}
                  onDoubleClick={() => useViewer.getState().show([it.id], 0)}
                  className={clsx('relative aspect-square cursor-pointer overflow-hidden rounded-lg border-2 bg-thumb', on ? 'border-accent' : 'border-transparent')}
                >
                  <img src={mediaUrl(`media/thumb/${it.id}?v=${it.v}`)} alt="" loading="lazy" className={clsx('size-full object-cover', it.priv && 'blur-private')} />
                  <span className={clsx('absolute right-1.5 top-1.5 flex size-5 items-center justify-center rounded-full border-2', on ? 'border-accent bg-accent text-white' : 'border-white bg-black/30 text-transparent')}>
                    {on ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" />}
                  </span>
                  <span className="absolute bottom-1 left-1 rounded bg-black/55 px-1 text-[10px] text-white">{Math.round(it.score * 100)}%</span>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );

  return <Timeline key={lid} scope={`label-${lid}`} filters={{ label_id: lid }} header={header} />;
}
