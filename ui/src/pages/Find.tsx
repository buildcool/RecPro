import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { ArrowLeft, ArrowRight, Check, ChevronDown, ChevronRight, Copy, FolderInput, FolderOpen, ImagePlus, Loader2, Lock, Search, ShieldCheck, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { Badge, Button, Card, EmptyState, Segmented, TextInput } from '../components/ui';
import { ModelSetupCard } from '../features/models/ModelSetup';
import { useCopyFlow } from '../features/ops/CopyFlow';
import { FaceAvatar } from '../features/people/FaceAvatar';
import { answerFaces } from '../features/people/actions';
import { usePrivateUi } from '../features/private/PrivateLock';
import { startTimes, useViewer } from '../features/viewer/viewerStore';
import { ApiError, mediaUrl, post, upload } from '../lib/api';
import { bridge } from '../lib/bridge';
import { clock, num } from '../lib/format';
import { useNamedPeople } from '../lib/people';
import { useFolders } from '../lib/queries';
import type { MediaItem } from '../lib/types';

type Hit = MediaItem & { tier: 'sure' | 'check'; score: number; face_id: number; person_id: number | null; person_name: string | null; folder: string };
type Result = {
  sure: Hit[];
  check: Hit[];
  groups: { folder: string; sure: number; check: number }[];
  hidden_private: number;
  hidden_more?: number; // photos from the same outings where the person's face may be hidden
  scanned: number;
  pending: number;
};
type RefFace = { token: string; crop: string; quality: number };

const STEPS = ['Who', 'Where', 'Check matches'] as const;

export function FindPage() {
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [people, setPeople] = useState<number[]>(() => (sp.get('person') ? [Number(sp.get('person'))] : []));
  const [refs, setRefs] = useState<RefFace[]>([]);
  const [mode, setMode] = useState<'any' | 'all' | 'alone'>('any');
  const { data: folders } = useFolders();
  const [folderIds, setFolderIds] = useState<number[] | null>(null);
  const [kinds, setKinds] = useState<'both' | 'image' | 'video'>('both');

  useEffect(() => {
    if (sp.get('person')) setStep(1);
  }, [sp]);

  const allFolders = folders?.map((f) => f.id) ?? [];
  const chosenFolders = folderIds ?? allFolders;
  const canNext = step === 0 ? people.length + refs.length > 0 : step === 1 ? chosenFolders.length > 0 : true;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-4 border-b border-line bg-surface px-6 py-3">
        <button type="button" className="text-fg-2 hover:text-fg" onClick={() => nav(-1)} aria-label="Back">
          <ArrowLeft className="size-5" />
        </button>
        <h1 className="text-[17px] font-semibold">Find and move</h1>
        <ol className="ml-4 flex items-center gap-2 text-[13px]">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-2">
              {i > 0 && <ChevronRight className="size-4 text-fg-3" />}
              <button
                type="button"
                disabled={i > step}
                onClick={() => setStep(i)}
                className={clsx('flex items-center gap-1.5 rounded-md px-1.5 py-0.5', i === step ? 'font-semibold text-fg' : i < step ? 'text-fg-2 hover:text-fg' : 'text-fg-3')}
              >
                <span className={clsx('flex size-5 items-center justify-center rounded-full text-[11px]', i < step ? 'bg-ok text-white' : i === step ? 'bg-accent text-white' : 'bg-surface-3')}>
                  {i < step ? <Check className="size-3" /> : i + 1}
                </span>
                {s}
              </button>
            </li>
          ))}
          <li className="flex items-center gap-2 text-fg-3">
            <ChevronRight className="size-4" />
            Copy or move
          </li>
        </ol>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {step === 0 && <WhoStep people={people} setPeople={setPeople} refs={refs} setRefs={setRefs} mode={mode} setMode={setMode} />}
        {step === 1 && (
          <WhereStep
            folders={folders ?? []}
            chosen={chosenFolders}
            setChosen={setFolderIds}
            kinds={kinds}
            setKinds={setKinds}
          />
        )}
        {step === 2 && (
          <CheckStep
            people={people}
            refs={refs}
            mode={mode}
            folderIds={chosenFolders}
            kinds={kinds === 'both' ? undefined : [kinds]}
          />
        )}
      </div>

      {step < 2 && (
        <div className="flex shrink-0 items-center justify-between border-t border-line bg-surface px-6 py-3">
          <Button variant="ghost" icon={<ArrowLeft className="size-4" />} disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            Back
          </Button>
          <Button variant="primary" size="lg" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
            {step === 1 ? 'Find matches' : 'Next'} <ArrowRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- step 1
function WhoStep({
  people,
  setPeople,
  refs,
  setRefs,
  mode,
  setMode,
}: {
  people: number[];
  setPeople: (v: number[]) => void;
  refs: RefFace[];
  setRefs: (v: RefFace[]) => void;
  mode: 'any' | 'all' | 'alone';
  setMode: (v: 'any' | 'all' | 'alone') => void;
}) {
  const { data: named } = useNamedPeople();
  const [q, setQ] = useState('');
  const [found, setFound] = useState<{ source: string; faces: RefFace[]; error: string | null }[]>([]);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const list = (named ?? []).filter((p) => !q.trim() || p.name?.toLowerCase().includes(q.trim().toLowerCase()));
  const targets = people.length + refs.length;

  const analyze = async (paths: string[] | null, files: File[] | null) => {
    setLoading(true);
    try {
      let res: { images: { source: string; faces: RefFace[]; error: string | null }[] };
      if (paths) res = await post('/api/search/ref-faces', { paths });
      else {
        const fd = new FormData();
        files!.forEach((f) => fd.append('files', f));
        res = await upload('/api/search/ref-faces', fd);
      }
      setFound(res.images);
      const single = res.images.flatMap((i) => i.faces);
      if (single.length === 1) setRefs([...refs, single[0]]);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-6">
      <ModelSetupCard need="faces" />
      <div>
        <h2 className="text-[22px] font-semibold tracking-tight">Who are you looking for?</h2>
        <p className="mt-1 text-sm text-fg-2">Pick one or more people, or use a photo of someone. You'll see every match before anything is copied.</p>
      </div>

      <Card className="p-4">
        <div className="mb-3 flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-fg-3" />
            <TextInput className="pl-8" placeholder="Search people" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Button
            icon={loading ? <Loader2 className="size-4 animate-spin" /> : <ImagePlus className="size-4" />}
            onClick={async () => {
              if (bridge?.engine) {
                const paths = await bridge.pickImages();
                if (paths.length) void analyze(paths, null);
              } else fileRef.current?.click();
            }}
          >
            Use a photo of them
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => {
              const files = [...(e.target.files ?? [])];
              if (files.length) void analyze(null, files);
              e.target.value = '';
            }}
          />
        </div>
        {(named?.length ?? 0) === 0 && <p className="py-4 text-sm text-fg-2">No named people yet. Name groups in People, or use a photo.</p>}
        <div className="grid max-h-[340px] grid-cols-[repeat(auto-fill,minmax(104px,1fr))] gap-2 overflow-y-auto">
          {list.map((p) => {
            const on = people.includes(p.id);
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => setPeople(on ? people.filter((x) => x !== p.id) : [...people, p.id])}
                className={clsx('relative flex flex-col items-center rounded-xl p-2 transition-colors', on ? 'bg-accent-soft' : 'hover:bg-surface-2')}
              >
                <FaceAvatar faceId={p.cover_face_id} size={64} className={clsx(on && 'ring-2 ring-accent')} />
                <span className="mt-1.5 w-full truncate text-[13px] font-medium">{p.name}</span>
                <span className="text-[11px] text-fg-3">{num(p.count)}</span>
                {on && (
                  <span className="absolute right-2 top-2 flex size-5 items-center justify-center rounded-full bg-accent text-white">
                    <Check className="size-3" strokeWidth={3} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </Card>

      {found.length > 0 && (
        <Card className="p-4">
          <div className="mb-2 text-sm font-semibold">Faces in your photo{found.length > 1 ? 's' : ''}: tap the person you mean</div>
          <div className="flex flex-wrap gap-3">
            {found.flatMap((img) =>
              img.faces.map((f) => {
                const on = refs.some((r) => r.token === f.token);
                return (
                  <button
                    key={f.token}
                    type="button"
                    onClick={() => setRefs(on ? refs.filter((r) => r.token !== f.token) : [...refs, f])}
                    className={clsx('relative rounded-xl p-1', on ? 'bg-accent-soft ring-2 ring-accent' : 'hover:bg-surface-2')}
                  >
                    <img src={f.crop} alt="" className="size-20 rounded-lg object-cover" />
                    {on && (
                      <span className="absolute right-1.5 top-1.5 flex size-5 items-center justify-center rounded-full bg-accent text-white">
                        <Check className="size-3" strokeWidth={3} />
                      </span>
                    )}
                  </button>
                );
              }),
            )}
            {found.filter((i) => i.error).map((i) => (
              <p key={i.source} className="text-[13px] text-warn">
                {i.source.split(/[\\/]/).pop()}: {i.error}
              </p>
            ))}
          </div>
        </Card>
      )}

      {targets > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium">In the photo:</span>
          <Segmented
            value={mode}
            onChange={setMode}
            options={
              targets > 1
                ? [
                    { value: 'any', label: 'Any of them' },
                    { value: 'all', label: 'All of them together' },
                  ]
                : [
                    { value: 'any', label: 'With anyone' },
                    { value: 'alone', label: 'Only them, alone' },
                  ]
            }
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------- step 2
function WhereStep({
  folders,
  chosen,
  setChosen,
  kinds,
  setKinds,
}: {
  folders: { id: number; path: string; photos: number; videos: number; online: boolean }[];
  chosen: number[];
  setChosen: (v: number[]) => void;
  kinds: 'both' | 'image' | 'video';
  setKinds: (v: 'both' | 'image' | 'video') => void;
}) {
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-6 py-6">
      <div>
        <h2 className="text-[22px] font-semibold tracking-tight">Where should RecPro look?</h2>
        <p className="mt-1 text-sm text-fg-2">Results show which folder every match is in.</p>
      </div>
      <Card className="divide-y divide-line">
        {folders.map((f) => {
          const on = chosen.includes(f.id);
          return (
            <label key={f.id} className="flex cursor-pointer items-center gap-3 px-4 py-3">
              <input
                type="checkbox"
                className="size-4 accent-[var(--accent)]"
                checked={on}
                onChange={() => setChosen(on ? chosen.filter((x) => x !== f.id) : [...chosen, f.id])}
              />
              <FolderOpen className="size-4 text-fg-3" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium" title={f.path}>
                {f.path}
              </span>
              <span className="text-xs text-fg-3">
                {num(f.photos)} photos · {num(f.videos)} videos
              </span>
            </label>
          );
        })}
      </Card>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium">Look in</span>
        <Segmented
          value={kinds}
          onChange={setKinds}
          options={[
            { value: 'both', label: 'Photos and videos' },
            { value: 'image', label: 'Photos' },
            { value: 'video', label: 'Videos' },
          ]}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- step 3
function CheckStep({ people, refs, mode, folderIds, kinds }: { people: number[]; refs: RefFace[]; mode: string; folderIds: number[]; kinds?: string[] }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const body = useMemo(() => ({ people, ref_tokens: refs.map((r) => r.token), mode, folder_ids: folderIds, kinds }), [people, refs, mode, folderIds, kinds]);
  const { data: res, isLoading } = useQuery({
    queryKey: ['search', 'people', body],
    queryFn: () => post<Result>('/api/search/people', body),
    refetchInterval: (q) => (q.state.data?.pending ? 4000 : false),
  });
  const [deselected, setDeselected] = useState<Set<number>>(new Set());
  const [checkYes, setCheckYes] = useState<Set<number>>(new Set());
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const askUnlock = usePrivateUi((s) => s.ask);
  const startCopy = useCopyFlow((s) => s.start);
  const { data: named } = useNamedPeople();

  if (isLoading || !res)
    return (
      <div className="flex h-full items-center justify-center gap-3 text-fg-2">
        <Loader2 className="size-5 animate-spin" /> Looking through your folders…
      </div>
    );

  const selected = res.sure.filter((h) => !deselected.has(h.id));
  const extra = res.check.filter((h) => checkYes.has(h.id));
  const chosenIds = [...selected, ...extra].map((h) => h.id);
  const personByMedia: Record<number, string> = {};
  [...selected, ...extra].forEach((h) => {
    if (h.person_name) personByMedia[h.id] = h.person_name;
  });
  const names = people.map((id) => named?.find((p) => p.id === id)?.name).filter(Boolean) as string[];
  const title = `${names.join(' & ') || 'Person from a photo'} · ${num(chosenIds.length)} items`;

  const confirmChecks = async () => {
    setSaving(true);
    try {
      const byPerson = new Map<number, { yes: number[]; no: number[] }>();
      for (const h of res.check) {
        if (h.person_id == null) continue;
        const e = byPerson.get(h.person_id) ?? { yes: [], no: [] };
        (checkYes.has(h.id) ? e.yes : e.no).push(h.face_id);
        byPerson.set(h.person_id, e);
      }
      let settled = 0;
      for (const [pid, { yes, no }] of byPerson) settled += (await answerFaces(pid, yes, no)).settled;
      toast.success(`Thanks, RecPro learned from ${num(res.check.length)} answers${settled ? ` and settled ${num(settled)} more` : ''}`);
      setCheckYes(new Set());
      qc.invalidateQueries({ queryKey: ['search'] });
      qc.invalidateQueries({ queryKey: ['review'] });
    } finally {
      setSaving(false);
    }
  };

  const groups = groupBy(res.sure, (h) => h.folder);
  const openViewer = (list: { id: number; at_ms?: number }[], id: number) => {
    const ids = list.map((x) => x.id);
    useViewer.getState().show(ids, Math.max(0, ids.indexOf(id)), startTimes(list));
  };

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <Badge tone="ok">
            <Check className="size-3" /> Sure · {num(res.sure.length)}
          </Badge>
          <Badge tone="warn">Please check · {num(res.check.length)}</Badge>
          {res.hidden_private > 0 && (
            <button type="button" onClick={askUnlock}>
              <Badge tone="private">
                <Lock className="size-3" /> Private · {num(res.hidden_private)} hidden · Unlock to include
              </Badge>
            </button>
          )}
          {!!res.hidden_more && people.length === 1 && (
            <button type="button" onClick={() => navigate(`/review?tab=hidden&person=${people[0]}`)} title="Photos from the same outings where someone is there but their face isn't visible">
              <Badge tone="neutral">Face not visible · {num(res.hidden_more)} maybe · Check</Badge>
            </button>
          )}
          <span className="ml-auto text-[13px] text-fg-2">
            Looked at {num(res.scanned)} items
            {res.pending > 0 && ` · still analyzing ${num(res.pending)}, results update live`}
          </span>
        </div>

        {res.sure.length + res.check.length === 0 && (
          <EmptyState
            title="No matches yet"
            body={res.pending ? 'Faces are still being analyzed in these folders. Matches appear here as they are found.' : 'Try other folders, or add more photos of this person in People.'}
          />
        )}

        {res.check.length > 0 && (
          <section className="mb-8 rounded-2xl border border-warn/30 bg-warn-soft/40 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h3 className="text-[15px] font-semibold">Please check these {num(res.check.length)}</h3>
              <span className="text-[13px] text-fg-2">RecPro isn't sure. Tick the ones that are right; your answers teach it.</span>
              <Button size="sm" className="ml-auto" variant="primary" loading={saving} onClick={() => void confirmChecks()}>
                Save answers
              </Button>
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-3">
              {res.check.map((h) => {
                const on = checkYes.has(h.id);
                return (
                  <div
                    key={h.id}
                    role="checkbox"
                    aria-checked={on}
                    tabIndex={0}
                    onClick={() => setCheckYes((s) => toggleSet(s, h.id))}
                    className={clsx('relative cursor-pointer rounded-xl border-2 bg-surface p-1.5', on ? 'border-accent' : 'border-transparent')}
                  >
                    <div className="flex gap-1">
                      <img src={mediaUrl(`media/face/${h.face_id}?size=160`)} alt="" className={clsx('aspect-square w-1/2 rounded-lg object-cover', h.priv && 'blur-private')} />
                      <img src={mediaUrl(`media/thumb/${h.id}?v=${h.v}`)} alt="" className={clsx('aspect-square w-1/2 rounded-lg object-cover', h.priv && 'blur-private')} />
                    </div>
                    <div className="mt-1 flex items-center justify-between px-0.5 text-[11px] text-fg-2">
                      <span>{h.person_name ?? 'Match'} · {Math.round(h.score * 100)}%</span>
                      <button type="button" className="text-accent-text hover:underline" onClick={(e) => { e.stopPropagation(); openViewer(res.check, h.id); }}>
                        View
                      </button>
                    </div>
                    <span className={clsx('absolute right-2.5 top-2.5 flex size-5 items-center justify-center rounded-full border-2', on ? 'border-accent bg-accent text-white' : 'border-white bg-black/30 text-transparent')}>
                      <Check className="size-3" strokeWidth={3} />
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {groups.map(([folder, hits]) => {
          const isCollapsed = collapsed.has(folder);
          const allOn = hits.every((h) => !deselected.has(h.id));
          return (
            <section key={folder} className="mb-6">
              <div className="mb-2 flex items-center gap-2">
                <button type="button" onClick={() => setCollapsed((s) => toggleSetStr(s, folder))} className="text-fg-3 hover:text-fg" aria-label="Collapse">
                  {isCollapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
                </button>
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--accent)]"
                  checked={allOn}
                  onChange={() =>
                    setDeselected((s) => {
                      const n = new Set(s);
                      hits.forEach((h) => (allOn ? n.add(h.id) : n.delete(h.id)));
                      return n;
                    })
                  }
                  aria-label={`Select all in ${folder}`}
                />
                <FolderOpen className="size-4 text-fg-3" />
                <span className="truncate text-sm font-semibold" title={folder}>
                  {folder}
                </span>
                <span className="text-[13px] text-fg-3">{num(hits.length)}</span>
              </div>
              {!isCollapsed && (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-1.5">
                  {hits.map((h) => {
                    const on = !deselected.has(h.id);
                    return (
                      <div key={h.id} className="group relative aspect-square cursor-pointer overflow-hidden rounded-md bg-thumb" onClick={() => openViewer(hits, h.id)}>
                        <img src={mediaUrl(`media/thumb/${h.id}?v=${h.v}`)} alt="" loading="lazy" className={clsx('size-full object-cover transition', !on && 'opacity-35 grayscale', h.priv && 'blur-private')} />
                        <button
                          type="button"
                          aria-label={on ? 'Leave out' : 'Include'}
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeselected((s) => toggleSet(s, h.id));
                          }}
                          className={clsx('absolute left-1.5 top-1.5 flex size-5 items-center justify-center rounded-full border-2', on ? 'border-accent bg-accent text-white' : 'border-white bg-black/30 text-transparent')}
                        >
                          <Check className="size-3" strokeWidth={3} />
                        </button>
                        {h.kind === 'video' && (
                          <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 text-[10px] text-white" title={momentsTitle(h.spans)}>
                            {h.at_ms != null ? `Video · at ${clock(h.at_ms)}` : 'Video'}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-line bg-surface px-6 py-3">
        <span className="flex items-center gap-1.5 text-[13px] text-fg-2">
          <ShieldCheck className="size-4 text-ok" /> {num(chosenIds.length)} chosen. Every copy is verified before anything is removed.
        </span>
        {res.check.length > 0 && checkYes.size === 0 && <span className="text-[13px] text-warn">Tip: check the {num(res.check.length)} unsure ones first.</span>}
        <span className="ml-auto" />
        {deselected.size > 0 && (
          <Button variant="ghost" icon={<X className="size-4" />} onClick={() => setDeselected(new Set())}>
            Reset selection
          </Button>
        )}
        <Button icon={<FolderInput className="size-4" />} disabled={!chosenIds.length} onClick={() => startCopy(chosenIds, 'move', { title, personIds: people, personByMedia })}>
          Move {num(chosenIds.length)}…
        </Button>
        <Button variant="primary" size="lg" icon={<Copy className="size-4" />} disabled={!chosenIds.length} onClick={() => startCopy(chosenIds, 'copy', { title, personIds: people, personByMedia })}>
          Copy {num(chosenIds.length)}…
        </Button>
      </div>
    </div>
  );
}

function groupBy<T>(xs: T[], key: (x: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  xs.forEach((x) => {
    const k = key(x);
    const a = m.get(k) ?? [];
    a.push(x);
    m.set(k, a);
  });
  return [...m.entries()];
}

function toggleSet(s: Set<number>, id: number) {
  const n = new Set(s);
  if (n.has(id)) n.delete(id);
  else n.add(id);
  return n;
}

function toggleSetStr(s: Set<string>, id: string) {
  const n = new Set(s);
  if (n.has(id)) n.delete(id);
  else n.add(id);
  return n;
}

/** "Colin Powell 0:00–0:08, 0:14–0:18" for a video's matched stretches. */
function momentsTitle(spans?: { name: string | null; start_ms: number; end_ms: number }[]): string | undefined {
  if (!spans?.length) return undefined;
  const by = new Map<string, string[]>();
  for (const sp of spans) {
    const k = sp.name ?? 'Match';
    by.set(k, [...(by.get(k) ?? []), `${clock(sp.start_ms)}–${clock(sp.end_ms)}`]);
  }
  return [...by].map(([k, v]) => `${k} ${v.join(', ')}`).join('; ');
}
