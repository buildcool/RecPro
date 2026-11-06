import * as Tabs from '@radix-ui/react-tabs';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { Check, CheckCircle2, MessageCircleQuestion, SkipForward, Undo2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { Badge, Button, EmptyState, Kbd, PageHeader } from '../components/ui';
import { FaceAvatar } from '../features/people/FaceAvatar';
import { NameInput } from '../features/people/NameInput';
import { answerFaces, namePerson } from '../features/people/actions';
import { useViewer } from '../features/viewer/viewerStore';
import { SensitiveReview } from '../features/private/SensitiveReview';
import { get, mediaUrl, post } from '../lib/api';
import { num } from '../lib/format';
import { type Brief, type ReviewFaces, useReviewCounts } from '../lib/people';

export function ReviewPage() {
  const { data: counts } = useReviewCounts();
  const [sp] = useSearchParams();
  const [tab, setTab] = useState(sp.get('tab') ?? 'faces');
  const tabs: [string, string, number | undefined][] = [
    ['faces', 'Is this…?', counts?.faces],
    ['merge', 'Same person?', counts?.merge],
    ['name', 'Who is this?', counts?.name],
    ['private', 'Private', counts?.sensitive],
  ];
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Review"
        subtitle="When RecPro isn't sure, it asks here instead of guessing. Every answer also settles similar photos."
      />
      <Tabs.Root value={tab} onValueChange={setTab} className="px-6 pb-12">
        <Tabs.List className="mb-5 inline-flex rounded-lg bg-surface-2 p-0.5" aria-label="Kinds of questions">
          {tabs.map(([v, l, n]) => (
            <Tabs.Trigger
              key={v}
              value={v}
              className="flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium text-fg-2 data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm"
            >
              {l}
              {!!n && <Badge tone="warn">{num(n)}</Badge>}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="faces">
          <FaceQuestions initialPerson={sp.get('person') ? Number(sp.get('person')) : undefined} />
        </Tabs.Content>
        <Tabs.Content value="merge">
          <MergeQuestions />
        </Tabs.Content>
        <Tabs.Content value="name">
          <NameQuestions />
        </Tabs.Content>
        <Tabs.Content value="private">
          <SensitiveReview />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

// ---------------------------------------------------------------------------- Is this X?
function FaceQuestions({ initialPerson }: { initialPerson?: number }) {
  const qc = useQueryClient();
  const [personId, setPersonId] = useState<number | undefined>(initialPerson);
  const { data, isLoading } = useQuery({
    queryKey: ['review', 'faces', personId ?? 'auto'],
    queryFn: () => get<ReviewFaces>(`/api/review/faces?limit=12${personId ? `&person_id=${personId}` : ''}`),
  });
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [focus, setFocus] = useState(0);
  const [busy, setBusy] = useState(false);
  const items = useMemo(() => data?.items ?? [], [data]);

  useEffect(() => {
    setTicked(new Set(items.filter((i) => i.probability >= 0.5).map((i) => i.face_id)));
    setFocus(0);
  }, [items]);

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['review'] });
    qc.invalidateQueries({ queryKey: ['people'] });
    qc.invalidateQueries({ queryKey: ['person'] });
  }, [qc]);

  const submit = useCallback(
    async (mode: 'ticked' | 'none') => {
      if (!data?.person || items.length === 0) return;
      setBusy(true);
      try {
        const yes = mode === 'none' ? [] : items.filter((i) => ticked.has(i.face_id)).map((i) => i.face_id);
        const no = items.filter((i) => !yes.includes(i.face_id)).map((i) => i.face_id);
        const r = await answerFaces(data.person.id, yes, no);
        if (r.settled > 0) toast.success(`Your answers settled ${num(r.settled)} more photos`);
        refresh();
      } finally {
        setBusy(false);
      }
    },
    [data, items, ticked, refresh],
  );

  const undo = useCallback(async () => {
    const r = await post<{ undone: boolean }>('/api/review/undo');
    if (r.undone) {
      toast('Last answer undone');
      refresh();
    }
  }, [refresh]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || useViewer.getState().open) return;
      const k = e.key.toLowerCase();
      if (k === 'y' || k === 'enter') {
        e.preventDefault();
        void submit('ticked');
      } else if (k === 'n') void submit('none');
      else if (k === 'z') void undo();
      else if (k === 's') setPersonId(undefined);
      else if (k === 'arrowright') setFocus((f) => Math.min(f + 1, items.length - 1));
      else if (k === 'arrowleft') setFocus((f) => Math.max(f - 1, 0));
      else if (k === ' ') {
        e.preventDefault();
        const it = items[focus];
        if (it) setTicked((t) => toggle(t, it.face_id));
      } else if (k === 'p') {
        const it = items[focus];
        if (it) useViewer.getState().show([it.media_id], 0);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [submit, undo, items, focus]);

  if (isLoading) return null;
  if (!data?.person || items.length === 0)
    return (
      <EmptyState
        icon={<CheckCircle2 className="size-6 text-ok" />}
        title="Nothing to check right now"
        body="When RecPro finds a face that might be someone you named, it asks here."
      />
    );

  return (
    <div className="max-w-5xl">
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <h2 className="text-[20px] font-semibold">Is this {data.person.name}?</h2>
        <div className="flex items-center gap-2 text-[13px] text-fg-2">
          Known:
          <span className="flex -space-x-2">
            {data.known.slice(0, 4).map((f) => (
              <FaceAvatar key={f} faceId={f} size={34} ring />
            ))}
          </span>
        </div>
        <span className="ml-auto text-[13px] text-fg-2">{num(data.remaining)} left for {data.person.name}</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        {items.map((it, i) => {
          const on = ticked.has(it.face_id);
          return (
            <div
              key={it.face_id}
              role="checkbox"
              aria-checked={on}
              tabIndex={0}
              onClick={() => {
                setFocus(i);
                setTicked((t) => toggle(t, it.face_id));
              }}
              className={clsx(
                'group relative cursor-pointer overflow-hidden rounded-2xl border-2 bg-surface p-2 transition-colors',
                on ? 'border-accent' : 'border-transparent',
                focus === i && 'ring-2 ring-accent/40',
              )}
            >
              <img src={mediaUrl(`media/face/${it.face_id}?size=256`)} alt="" className={clsx('aspect-square w-full rounded-xl object-cover', it.private && 'blur-private')} draggable={false} />
              <div className="mt-2 flex items-center justify-between gap-2 text-xs">
                <span className={clsx('font-medium', it.probability >= 0.5 ? 'text-fg' : 'text-fg-3')}>{Math.round(it.probability * 100)}% likely</span>
                <button
                  type="button"
                  className="text-accent-text hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    useViewer.getState().show([it.media_id], 0);
                  }}
                >
                  Photo
                </button>
              </div>
              <span
                className={clsx(
                  'absolute right-3 top-3 flex size-7 items-center justify-center rounded-full border-2',
                  on ? 'border-accent bg-accent text-white' : 'border-white/90 bg-black/30 text-transparent',
                )}
              >
                <Check className="size-4" strokeWidth={3} />
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button variant="primary" loading={busy} icon={<Check className="size-4" />} onClick={() => void submit('ticked')}>
          {ticked.size === items.length ? `All ${items.length} are ${data.person.name}` : `Yes to ${ticked.size}, no to ${items.length - ticked.size}`}
        </Button>
        <Button icon={<X className="size-4" />} onClick={() => void submit('none')}>
          None of these
        </Button>
        <Button variant="ghost" icon={<SkipForward className="size-4" />} onClick={() => setPersonId(undefined)}>
          Someone else
        </Button>
        <Button variant="ghost" icon={<Undo2 className="size-4" />} onClick={() => void undo()}>
          Undo
        </Button>
        <span className="ml-auto flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
          <Kbd>Y</Kbd> confirm <Kbd>N</Kbd> none <Kbd>Space</Kbd> tick <Kbd>P</Kbd> photo <Kbd>Z</Kbd> undo
        </span>
      </div>
    </div>
  );
}

function toggle(s: Set<number>, id: number) {
  const n = new Set(s);
  if (n.has(id)) n.delete(id);
  else n.add(id);
  return n;
}

// ---------------------------------------------------------------------------- Same person?
function MergeQuestions() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['review', 'merge'], queryFn: () => get<{ similarity: number; a: Brief; b: Brief }[]>('/api/review/merge') });
  if (!data || data.length === 0)
    return <EmptyState icon={<CheckCircle2 className="size-6 text-ok" />} title="No look-alikes to compare" body="When two groups might be the same person, RecPro asks here." />;
  const answer = async (a: number, b: number, same: boolean) => {
    await post('/api/review/merge/answer', { a, b, same });
    if (same) toast.success('Merged into one person');
    qc.invalidateQueries({ queryKey: ['review'] });
    qc.invalidateQueries({ queryKey: ['people'] });
  };
  return (
    <div className="max-w-4xl space-y-4">
      {data.map((pair) => (
        <div key={`${pair.a.id}-${pair.b.id}`} className="rounded-2xl border border-line bg-surface p-4">
          <div className="mb-3 text-[15px] font-semibold">Same person?</div>
          <div className="grid grid-cols-2 gap-4">
            {[pair.a, pair.b].map((p) => (
              <div key={p.id} className="rounded-xl bg-surface-2 p-3">
                <div className="mb-2 text-sm font-medium">{p.name ?? 'Unnamed'} <span className="text-fg-3">· {num(p.count)} photos</span></div>
                <div className="flex gap-2">
                  {p.faces.slice(0, 4).map((f) => (
                    <FaceAvatar key={f} faceId={f} size={64} />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => void answer(pair.a.id, pair.b.id, true)}>
              Yes, same person
            </Button>
            <Button onClick={() => void answer(pair.a.id, pair.b.id, false)}>No, different people</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------- Who is this?
function NameQuestions() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['review', 'name'], queryFn: () => get<Brief[]>('/api/review/name') });
  if (!data || data.length === 0)
    return (
      <EmptyState
        icon={<MessageCircleQuestion className="size-6" />}
        title="Everyone found so far has a name"
        body="New groups of faces show up here as more photos are analyzed."
      />
    );
  return (
    <div className="grid max-w-5xl grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
      {data.map((p) => (
        <div key={p.id} className="rounded-2xl border border-line bg-surface p-4">
          <div className="mb-3 flex gap-2">
            {p.faces.slice(0, 4).map((f) => (
              <FaceAvatar key={f} faceId={f} size={56} />
            ))}
          </div>
          <div className="mb-2 text-xs text-fg-3">{num(p.count)} photos</div>
          <NameInput
            placeholder="Who is this?"
            onSubmit={async ({ name, personId }) => {
              await namePerson(p.id, name, personId);
              qc.invalidateQueries({ queryKey: ['review'] });
              qc.invalidateQueries({ queryKey: ['people'] });
            }}
          />
        </div>
      ))}
    </div>
  );
}
