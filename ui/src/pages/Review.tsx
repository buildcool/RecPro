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
import { type Brief, type Kind, type ReviewFaces, useReviewCounts } from '../lib/people';
import type { MediaItem } from '../lib/types';

export function ReviewPage() {
  const { data: counts } = useReviewCounts();
  const [sp] = useSearchParams();
  const [tab, setTab] = useState(sp.get('tab') ?? 'faces');
  const tabs: [string, string, number | undefined][] = [
    ['faces', 'Is this…?', counts?.faces],
    ['merge', 'Same person?', counts?.merge],
    ['name', 'Who is this?', counts?.name],
    ['hidden', 'Face hidden?', undefined],
    ['pets', 'Pets', counts ? (counts.pets ?? 0) + (counts.pet_name ?? 0) + (counts.pet_merge ?? 0) : undefined],
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
          <FaceQuestions initialPerson={sp.get('tab') !== 'pets' && sp.get('person') ? Number(sp.get('person')) : undefined} />
        </Tabs.Content>
        <Tabs.Content value="merge">
          <MergeQuestions />
        </Tabs.Content>
        <Tabs.Content value="name">
          <NameQuestions />
        </Tabs.Content>
        <Tabs.Content value="hidden">
          <HiddenQuestions initialPerson={sp.get('person') ? Number(sp.get('person')) : undefined} />
        </Tabs.Content>
        <Tabs.Content value="pets" className="space-y-10">
          <FaceQuestions kind="pet" initialPerson={sp.get('tab') === 'pets' && sp.get('person') ? Number(sp.get('person')) : undefined} />
          <NameQuestions kind="pet" quiet />
          <MergeQuestions kind="pet" quiet />
        </Tabs.Content>
        <Tabs.Content value="private">
          <SensitiveReview />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

// ---------------------------------------------------------------------------- Is this X?
function FaceQuestions({ initialPerson, kind = 'human' }: { initialPerson?: number; kind?: Kind }) {
  const qc = useQueryClient();
  const [personId, setPersonId] = useState<number | undefined>(initialPerson);
  const pet = kind === 'pet';
  const { data, isLoading } = useQuery({
    queryKey: ['review', 'faces', kind, personId ?? 'auto'],
    queryFn: () => get<ReviewFaces>(`/api/review/faces?limit=12&kind=${kind}${personId ? `&person_id=${personId}` : ''}`),
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
        title={pet ? 'No pets to check right now' : 'Nothing to check right now'}
        body={pet ? 'When RecPro finds an animal that might be a pet you named, it asks here.' : 'When RecPro finds a face that might be someone you named, it asks here.'}
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
              <FaceAvatar key={f} faceId={f} size={34} ring kind={kind} />
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
              <img
                src={mediaUrl(`media/${pet ? 'animal' : 'face'}/${it.face_id}?size=256`)}
                alt=""
                className={clsx('aspect-square w-full rounded-xl object-cover', it.private && 'blur-private')}
                draggable={false}
              />
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
          {pet ? 'Another pet' : 'Someone else'}
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
function MergeQuestions({ kind = 'human', quiet }: { kind?: Kind; quiet?: boolean }) {
  const qc = useQueryClient();
  const pet = kind === 'pet';
  const { data } = useQuery({
    queryKey: ['review', 'merge', kind],
    queryFn: () => get<{ similarity: number; a: Brief; b: Brief }[]>(`/api/review/merge?kind=${kind}`),
  });
  if (!data || data.length === 0)
    return quiet ? null : (
      <EmptyState icon={<CheckCircle2 className="size-6 text-ok" />} title="No look-alikes to compare" body="When two groups might be the same person, RecPro asks here." />
    );
  const answer = async (a: number, b: number, same: boolean) => {
    await post('/api/review/merge/answer', { a, b, same });
    if (same) toast.success(pet ? 'Merged into one pet' : 'Merged into one person');
    qc.invalidateQueries({ queryKey: ['review'] });
    qc.invalidateQueries({ queryKey: ['people'] });
  };
  return (
    <div className="max-w-4xl space-y-4">
      {data.map((pair) => (
        <div key={`${pair.a.id}-${pair.b.id}`} className="rounded-2xl border border-line bg-surface p-4">
          <div className="mb-3 text-[15px] font-semibold">{pet ? 'Same pet?' : 'Same person?'}</div>
          <div className="grid grid-cols-2 gap-4">
            {[pair.a, pair.b].map((p) => (
              <div key={p.id} className="rounded-xl bg-surface-2 p-3">
                <div className="mb-2 text-sm font-medium">{p.name ?? 'Unnamed'} <span className="text-fg-3">· {num(p.count)} photos</span></div>
                <div className="flex gap-2">
                  {p.faces.slice(0, 4).map((f) => (
                    <FaceAvatar key={f} faceId={f} size={64} kind={kind} />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => void answer(pair.a.id, pair.b.id, true)}>
              {pet ? 'Yes, same pet' : 'Yes, same person'}
            </Button>
            <Button onClick={() => void answer(pair.a.id, pair.b.id, false)}>{pet ? 'No, different pets' : 'No, different people'}</Button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------- Who is this?
function NameQuestions({ kind = 'human', quiet }: { kind?: Kind; quiet?: boolean }) {
  const qc = useQueryClient();
  const pet = kind === 'pet';
  const { data } = useQuery({ queryKey: ['review', 'name', kind], queryFn: () => get<Brief[]>(`/api/review/name?kind=${kind}`) });
  if (!data || data.length === 0)
    return quiet ? null : (
      <EmptyState
        icon={<MessageCircleQuestion className="size-6" />}
        title="Everyone found so far has a name"
        body="New groups of faces show up here as more photos are analyzed."
      />
    );
  return (
    <div className="max-w-5xl">
      {pet && <h2 className="mb-3 text-[17px] font-semibold">Whose pet is this?</h2>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
        {data.map((p) => (
          <div key={p.id} className="rounded-2xl border border-line bg-surface p-4">
            <div className="mb-3 flex gap-2">
              {p.faces.slice(0, 4).map((f) => (
                <FaceAvatar key={f} faceId={f} size={56} kind={kind} />
              ))}
            </div>
            <div className="mb-2 text-xs text-fg-3">{num(p.count)} photos</div>
            <NameInput
              kind={kind}
              placeholder={pet ? 'Name this pet' : 'Who is this?'}
              onSubmit={async ({ name, personId }) => {
                await namePerson(p.id, name, personId);
                qc.invalidateQueries({ queryKey: ['review'] });
                qc.invalidateQueries({ queryKey: ['people'] });
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- Face hidden?
type HiddenPerson = { id: number; name: string; cover_face_id: number | null; count: number };
type HiddenItem = MediaItem & { minutes: number; presence: number };

function HiddenQuestions({ initialPerson }: { initialPerson?: number }) {
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ['review', 'hidden'], queryFn: () => get<HiddenPerson[]>('/api/review/hidden') });
  const [picked, setPicked] = useState<number | undefined>(initialPerson);
  const active = picked ?? people.data?.[0]?.id;
  const data = useQuery({
    queryKey: ['review', 'hidden', active],
    queryFn: () => get<{ person: { id: number; name: string }; items: HiddenItem[] }>(`/api/review/hidden/${active}?limit=48`),
    enabled: active != null,
  });
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  useEffect(() => setTicked(new Set()), [active, data.data]);

  if (people.isLoading) return null;
  if (!people.data?.length && !initialPerson)
    return <EmptyState icon={<CheckCircle2 className="size-6" />} title="Nothing to check" body="When someone may be in a photo with their face turned away, RecPro asks here." />;
  const items = data.data?.items ?? [];
  const name = data.data?.person.name ?? people.data?.find((p) => p.id === active)?.name ?? '';

  const save = async (all: 'ticked' | 'none') => {
    if (active == null || !items.length) return;
    setSaving(true);
    try {
      const yes = all === 'none' ? [] : items.filter((i) => ticked.has(i.id)).map((i) => i.id);
      const no = items.filter((i) => !yes.includes(i.id)).map((i) => i.id);
      await post(`/api/review/hidden/${active}/answer`, { yes, no });
      toast(yes.length ? `${name} is in ${num(yes.length)} more ${yes.length === 1 ? 'photo' : 'photos'}` : `Noted: ${name} isn't in these`);
      qc.invalidateQueries({ queryKey: ['review', 'hidden'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {(people.data ?? []).map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setPicked(p.id)}
            className={clsx('flex items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-[13px]', p.id === active ? 'border-accent bg-accent/10 text-fg' : 'border-line text-fg-2 hover:bg-surface-2')}
          >
            <FaceAvatar faceId={p.cover_face_id} size={24} />
            {p.name}
            <span className="text-xs text-fg-3">{num(p.count)}</span>
          </button>
        ))}
      </div>
      {active != null && (
        <>
          <p className="mb-4 max-w-2xl text-sm text-fg-2">
            These are from the same outings as photos of <span className="font-medium text-fg">{name}</span>, and someone is in them, but no face in them is {name}'s. Tick
            the ones {name} is in; the rest count as "not in it".
          </p>
          {items.length === 0 && !data.isLoading ? (
            <EmptyState icon={<CheckCircle2 className="size-6" />} title="All checked" body={`Nothing left to check for ${name}.`} />
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
              {items.map((it) => {
                const on = ticked.has(it.id);
                return (
                  <div key={it.id} className="group relative overflow-hidden rounded-lg bg-thumb">
                    <button
                      type="button"
                      className="block aspect-square w-full"
                      aria-label={on ? `${name} is in this photo` : 'Tick if they are in this photo'}
                      onClick={() => setTicked((s) => {
                        const n = new Set(s);
                        if (n.has(it.id)) n.delete(it.id);
                        else n.add(it.id);
                        return n;
                      })}
                      onDoubleClick={() => useViewer.getState().show(items.map((x) => x.id), items.indexOf(it))}
                    >
                      <img src={mediaUrl(`media/thumb/${it.id}?v=${it.v}`)} alt="" loading="lazy" className={clsx('size-full object-cover', it.priv && 'blur-private')} />
                    </button>
                    <span className={clsx('pointer-events-none absolute left-1.5 top-1.5 flex size-6 items-center justify-center rounded-full border-2', on ? 'border-accent bg-accent text-white' : 'border-white bg-black/30 text-transparent')}>
                      <Check className="size-3.5" strokeWidth={3} />
                    </span>
                    <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-2 pb-1.5 pt-4 text-[11px] text-white">
                      {it.minutes < 1 ? 'Same moment' : `${num(it.minutes)} min from a photo of ${name}`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          {items.length > 0 && (
            <div className="sticky bottom-0 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-bg py-3">
              <Button variant="primary" loading={saving} disabled={!ticked.size} onClick={() => void save('ticked')} icon={<Check className="size-4" />}>
                {name} is in the {num(ticked.size)} ticked
              </Button>
              <Button loading={saving} onClick={() => void save('none')} icon={<X className="size-4" />}>
                Not in any of these
              </Button>
              <span className="text-xs text-fg-3">Double-click a photo to see it larger.</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
