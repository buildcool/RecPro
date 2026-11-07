import { useQuery } from '@tanstack/react-query';
import { Calendar, Film, FolderOpen, Lock, MapPin, Search as SearchIcon, Smile, Tag, UserRound, Users, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { Badge, EmptyState, Spinner, TextInput } from '../components/ui';
import { FlatGrid } from '../features/grid/FlatGrid';
import { usePrivateUi } from '../features/private/PrivateLock';
import { SaveSearch, useSavedSearches } from '../features/search/saved';
import { post } from '../lib/api';
import { num } from '../lib/format';
import type { MediaItem } from '../lib/types';

type Parsed = {
  people: { id: number; name: string }[];
  years: number[];
  months: number[];
  kind: string | null;
  age: [number, number] | null;
  gender: string | null;
  emotion: string | null;
  size: [number, number] | null;
  labels: { id: number; name: string }[];
  folders: { id: number; name: string }[];
  places?: { name: string; ids: number[] }[];
  text: string;
};
type Result = { parsed: Parsed; sure: MediaItem[]; check: MediaItem[]; hidden_private: number; refused?: string; took_ms: number };

const MONTH = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export function SearchPage() {
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') ?? '';
  const sid = Number(sp.get('s')) || null; // opened from a saved search: its chips as you left them
  const [draft, setDraft] = useState(q);
  const [removed, setRemoved] = useState<Record<string, unknown>>({});
  const nav = useNavigate();
  const ask = usePrivateUi((s) => s.ask);
  const { data: saved } = useSavedSearches();
  const opened = saved?.find((s) => s.id === sid && s.q === q) ?? null;
  useEffect(() => {
    setDraft(q);
    setRemoved(opened?.overrides ?? {});
  }, [q, opened?.id]); // not on every change of `opened`: your own chip changes would be undone

  const { data, isFetching } = useQuery({
    queryKey: ['search', 'text', q, removed],
    queryFn: () => post<Result>('/api/search', { q, overrides: Object.keys(removed).length ? removed : null }),
    enabled: !!q.trim(),
  });

  const chips = useMemo(() => {
    const p = data?.parsed;
    if (!p) return [];
    const out: { key: string; icon: React.ReactNode; label: string; remove: Record<string, unknown> }[] = [];
    p.people.forEach((x) => out.push({ key: `p${x.id}`, icon: <UserRound className="size-3.5" />, label: x.name, remove: { people: p.people.filter((y) => y.id !== x.id) } }));
    if (p.years.length) out.push({ key: 'years', icon: <Calendar className="size-3.5" />, label: p.years.join(', '), remove: { years: [] } });
    if (p.months.length) out.push({ key: 'months', icon: <Calendar className="size-3.5" />, label: p.months.map((m) => MONTH[m]).join(', '), remove: { months: [] } });
    if (p.kind) out.push({ key: 'kind', icon: <Film className="size-3.5" />, label: p.kind === 'video' ? 'Videos' : 'Photos', remove: { kind: null } });
    if (p.gender || p.age)
      out.push({
        key: 'who',
        icon: <Users className="size-3.5" />,
        label: [p.gender === 'female' ? 'Female' : p.gender === 'male' ? 'Male' : '', p.age ? `age ${p.age[0]}–${p.age[1] >= 120 ? '+' : p.age[1]}` : ''].filter(Boolean).join(', '),
        remove: { gender: null, age: null },
      });
    if (p.size) out.push({ key: 'size', icon: <Users className="size-3.5" />, label: p.size[0] === 1 && p.size[1] === 1 ? 'Alone' : p.size[0] === 2 && p.size[1] === 2 ? 'Two people' : `${p.size[0]}+ people`, remove: { size: null } });
    if (p.emotion) out.push({ key: 'emo', icon: <Smile className="size-3.5" />, label: p.emotion, remove: { emotion: null } });
    p.labels.forEach((l) => out.push({ key: `l${l.id}`, icon: <Tag className="size-3.5" />, label: l.name, remove: { labels: [] } }));
    p.folders.forEach((f) => out.push({ key: `f${f.id}`, icon: <FolderOpen className="size-3.5" />, label: f.name, remove: { folders: [] } }));
    (p.places ?? []).forEach((pl, i) =>
      out.push({ key: `pl${i}`, icon: <MapPin className="size-3.5" />, label: pl.name, remove: { places: (p.places ?? []).filter((_, j) => j !== i) } }),
    );
    if (p.text && !p.labels.length) out.push({ key: 'text', icon: <SearchIcon className="size-3.5" />, label: `“${p.text}”`, remove: { text: '' } });
    return out;
  }, [data]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="px-6 pb-3 pt-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) setSp({ q: draft.trim() });
          }}
          className="relative flex max-w-3xl gap-2"
        >
          <SearchIcon className="pointer-events-none absolute left-3 top-3 size-5 text-fg-3" />
          <TextInput
            className="h-11 flex-1 pl-10 text-[15px]"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Rohit and Mom at the beach 2023 · laptop on a sofa · happy girls · screenshots of payments"
            autoFocus
          />
          {q && data && !data.refused && (
            <div className="flex items-center">
              <SaveSearch q={q} removed={removed} onSaved={(s) => setSp({ q: s.q, s: String(s.id) })} />
            </div>
          )}
        </form>
        {chips.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-fg-3">Understood as</span>
            {chips.map((c) => (
              <span key={c.key} className="flex items-center gap-1.5 rounded-full bg-accent-soft py-1 pl-2.5 pr-1.5 text-[13px] text-accent-text">
                {c.icon}
                {c.label}
                <button type="button" aria-label={`Remove ${c.label}`} className="rounded-full p-0.5 hover:bg-accent/15" onClick={() => setRemoved((r) => ({ ...r, ...c.remove }))}>
                  <X className="size-3" />
                </button>
              </span>
            ))}
            {isFetching && <Spinner />}
          </div>
        )}
      </div>
      <div className="px-6 pb-12">
        {!q && <EmptyState icon={<SearchIcon className="size-6" />} title="Search everything" body="People, places, activities, things, years, text in photos. Combine them freely." />}
        {data?.refused && <EmptyState icon={<Lock className="size-6" />} title="That search isn't allowed" body={data.refused} />}
        {data && !data.refused && (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[13px] text-fg-2">
              <Badge tone="ok">Best matches · {num(data.sure.length)}</Badge>
              {data.check.length > 0 && <Badge tone="warn">Maybe · {num(data.check.length)}</Badge>}
              {data.hidden_private > 0 && (
                <button type="button" onClick={ask}>
                  <Badge tone="private">
                    <Lock className="size-3" /> {num(data.hidden_private)} private hidden · Unlock to include
                  </Badge>
                </button>
              )}
              <span className="ml-auto text-xs text-fg-3">{data.took_ms} ms, on this PC</span>
            </div>
            {data.sure.length + data.check.length === 0 && (
              <EmptyState
                title="Nothing found"
                body="Try fewer words, or remove a chip above."
                actions={
                  <button type="button" className="text-sm text-accent-text hover:underline" onClick={() => nav('/explore')}>
                    Browse categories
                  </button>
                }
              />
            )}
            {data.sure.length > 0 && <FlatGrid items={data.sure} scope={`search-${q}`} />}
            {data.check.length > 0 && (
              <>
                <h3 className="mb-2 mt-8 text-[15px] font-semibold">Maybe</h3>
                <FlatGrid items={data.check} scope={`search-${q}`} />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
