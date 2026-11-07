import { useQuery } from '@tanstack/react-query';
import { ArrowRightLeft, CalendarHeart, Copy, Luggage, MapPin } from 'lucide-react';
import { useMemo } from 'react';
import { Link, useParams } from 'react-router';
import { Button, EmptyState, PageHeader } from '../components/ui';
import { FlatGrid } from '../features/grid/FlatGrid';
import { type Memory, MemoryCard, type MemoryDetail, useMemories } from '../features/memories/memories';
import { useCopyFlow } from '../features/ops/CopyFlow';
import { ApiError, get } from '../lib/api';
import { dateRange, num, weekday } from '../lib/format';

const byYear = (ms: Memory[]) => {
  const out = new Map<number, Memory[]>();
  for (const m of ms) {
    const y = new Date(m.start * 1000).getFullYear();
    out.set(y, [...(out.get(y) ?? []), m]);
  }
  return [...out.entries()];
};

/** Every trip and event, newest first, by year. */
export function MemoriesPage() {
  const { data, isLoading } = useMemories();
  const all = useMemo(() => [...(data?.trips ?? []), ...(data?.events ?? [])].sort((a, b) => b.start - a.start), [data]);
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Trips and events"
        subtitle={
          data?.home
            ? `Trips are the days 50 km or more from home (${data.home.name}); events are celebrations in your photos. Found on this PC.`
            : 'Trips are the days away from home; events are celebrations in your photos. Found on this PC.'
        }
      />
      <div className="space-y-8 px-6 pb-12">
        {!isLoading && all.length === 0 && (
          <EmptyState
            icon={<Luggage className="size-6" />}
            title="No trips or events yet"
            body="Trips appear for photos with a location taken away from home. Events appear for a few hours of photos of a wedding, a birthday, a festival, a party or a concert."
          />
        )}
        {byYear(all).map(([year, ms]) => (
          <section key={year}>
            <h2 className="mb-3 text-[15px] font-semibold">{year}</h2>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-3">
              {ms.map((m) => (
                <MemoryCard key={m.key} m={m} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

/** One trip or event, day by day. */
export function MemoryPage() {
  const { key = '' } = useParams();
  const { data, error, isLoading } = useQuery({
    queryKey: ['memories', 'one', key],
    queryFn: () => get<MemoryDetail>(`/api/memories/${key}`),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
  const start = useCopyFlow((s) => s.start);
  if (isLoading) return null;
  if (!data)
    return (
      <div className="h-full overflow-y-auto px-6 pt-6">
        <EmptyState
          icon={<CalendarHeart className="size-6" />}
          title="This trip or event isn't there any more"
          body={error instanceof ApiError ? error.message : 'Its photos may have been moved, or are private while Private is locked.'}
          actions={
            <Link to="/memories" className="text-sm text-accent-text hover:underline">
              All trips and events
            </Link>
          }
        />
      </div>
    );
  const m = data.memory;
  const ids = data.days.flatMap((d) => d.items.map((i) => i.id));
  const year = new Date(m.start * 1000).getFullYear();
  const what = m.kind === 'trip' ? (m.days === 1 ? 'Day trip' : 'Trip') : 'Event';
  const send = (mode: 'copy' | 'move') => start(ids, mode, { title: `${m.name} ${year}` });
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title={m.name}
        subtitle={`${what} · ${dateRange(m.start, m.end)}${m.days > 1 ? ` · ${m.days} days` : ''} · ${num(m.n)} ${m.n === 1 ? 'photo' : 'photos and videos'}`}
        actions={
          <>
            <Button icon={<Copy className="size-4" />} onClick={() => send('copy')}>
              Copy…
            </Button>
            <Button icon={<ArrowRightLeft className="size-4" />} onClick={() => send('move')}>
              Move…
            </Button>
          </>
        }
      />
      <div className="space-y-7 px-6 pb-12">
        {m.towns && m.towns.length > 0 && (
          <div className="flex flex-wrap gap-2" aria-label="Places on this trip">
            {m.towns.map((t) => (
              <Link
                key={t.id}
                to={`/places?city=${t.id}`}
                className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[13px] hover:bg-surface-2"
              >
                <MapPin className="size-3.5 text-fg-3" />
                {t.name}
                <span className="text-fg-3">{num(t.n)}</span>
              </Link>
            ))}
          </div>
        )}
        {data.days.map((d, i) => (
          <section key={d.date}>
            <h2 className="mb-3 flex flex-wrap items-baseline gap-x-2 text-[15px] font-semibold">
              {data.days.length > 1 && <span>Day {i + 1}</span>}
              <span className={data.days.length > 1 ? 'font-normal text-fg-2' : ''}>{weekday(d.date)}</span>
              {d.place && <span className="text-[13px] font-normal text-fg-3">· {d.place}</span>}
            </h2>
            <FlatGrid items={d.items} scope={`memory-${key}`} />
          </section>
        ))}
      </div>
    </div>
  );
}
