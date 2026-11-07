import { useQuery, useQueryClient } from '@tanstack/react-query';
import { House, Luggage, MapPin } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Button, EmptyState, PageHeader } from '../components/ui';
import { FlatGrid } from '../features/grid/FlatGrid';
import { useMemories } from '../features/memories/memories';
import { type PlaceRow, type PlacesResult, placeName } from '../features/places/places';
import { type Bounds, type MapView, WorldMap } from '../features/places/WorldMap';
import { get, mediaUrl, patch } from '../lib/api';
import { num } from '../lib/format';
import type { MediaItem } from '../lib/types';

const PAGE = 300;

const yearSpan = (a: number | null, b: number | null) => {
  if (!a || !b) return '';
  const y0 = new Date(a * 1000).getFullYear();
  const y1 = new Date(b * 1000).getFullYear();
  return y0 === y1 ? String(y0) : `${y0}–${y1}`;
};

/** Home decides what counts as a trip: worked out from the photos unless you pick it. */
function HomeChooser({ places }: { places: PlaceRow[] }) {
  const { data } = useMemories();
  const qc = useQueryClient();
  const home = data?.home;
  if (!home) return null;
  const choose = async (v: string) => {
    await patch('/api/settings', { 'places.home_city_id': v ? Number(v) : null });
    qc.invalidateQueries({ queryKey: ['memories'] });
    qc.invalidateQueries({ queryKey: ['settings'] });
  };
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] text-fg-2">
      <label className="flex items-center gap-2">
        <House className="size-4 text-fg-3" />
        Home
        <select
          value={home.chosen ? String(home.id) : ''}
          onChange={(e) => void choose(e.target.value)}
          className="h-8 max-w-[260px] rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-fg focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          <option value="">{home.chosen ? 'Work it out from my photos' : `${home.name} (from your photos)`}</option>
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              {placeName(p)}
            </option>
          ))}
        </select>
      </label>
      <span className="text-fg-3">Trips are the days 50 km or more from home.</span>
      {(data.trips.length > 0 || data.events.length > 0) && (
        <Link to="/memories" className="flex items-center gap-1 text-accent-text hover:underline">
          <Luggage className="size-3.5" /> {num(data.trips.length)} {data.trips.length === 1 ? 'trip' : 'trips'}
        </Link>
      )}
    </div>
  );
}

function boundsOf(ps: PlaceRow[]): Bounds {
  return [Math.min(...ps.map((p) => p.lat)), Math.min(...ps.map((p) => p.lon)), Math.max(...ps.map((p) => p.lat)), Math.max(...ps.map((p) => p.lon))];
}

export function PlacesPage() {
  const { data, isLoading } = useQuery({ queryKey: ['places', 'list'], queryFn: () => get<PlacesResult>('/api/places') });
  const [sp] = useSearchParams();
  const [view, setView] = useState<MapView | null>(null);
  const [focus, setFocus] = useState<{ bounds: Bounds; key: number } | null>(null);
  const [more, setMore] = useState<{ key: string; limit: number }>({ key: '', limit: PAGE });

  // the first look: everywhere there are photos; a town asked for (?city=, from a photo's details) whenever it changes
  const city = sp.get('city');
  const fitted = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (!data?.places.length || fitted.current === city) return;
    fitted.current = city;
    const pick = data.places.find((p) => p.id === Number(city));
    setFocus({ bounds: boundsOf(pick ? [pick] : data.places), key: Date.now() });
  }, [data, city]);

  const box = view ? [view.s, view.w, view.n, view.e].map((x) => x.toFixed(4)) : null;
  const boxKey = box?.join(',') ?? '';
  const limit = more.key === boxKey ? more.limit : PAGE;
  const media = useQuery({
    queryKey: ['places', 'media', boxKey, limit],
    queryFn: () => get<{ total: number; items: MediaItem[] }>(`/api/places/media?s=${box![0]}&w=${box![1]}&n=${box![2]}&e=${box![3]}&limit=${limit}`),
    enabled: !!box && !!data?.places.length,
    placeholderData: (prev) => prev,
  });

  const places = data?.places ?? [];
  const inView = useMemo(
    () => (view ? places.filter((p) => p.lat >= view.s && p.lat <= view.n && p.lon >= view.w && p.lon <= view.e) : places),
    [places, view],
  );
  const one = inView.length === 1 ? inView[0] : null;
  const title = one ? placeName(one) : !view || view.world ? 'Everywhere' : `${num(inView.length)} places in this area`;
  const total = media.data?.total ?? 0;

  if (!isLoading && places.length === 0)
    return (
      <div className="h-full overflow-y-auto">
        <PageHeader title="Places" subtitle="Where your photos were taken, named on this PC." />
        <div className="px-6 pb-12">
          <EmptyState
            icon={<MapPin className="size-6" />}
            title="No photos with a location yet"
            body="Phones save where each photo was taken when location is on in the camera app. RecPro names the place on this PC from a built-in list of towns; nothing is looked up online."
          />
        </div>
      </div>
    );

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Places"
        subtitle={
          data
            ? `${num(data.located)} photos and videos have a place, named on this PC: no location ever leaves it.${
                data.with_gps > data.located ? ` ${num(data.with_gps - data.located)} more were far from any town.` : ''
              }`
            : 'Where your photos were taken, named on this PC.'
        }
      />
      <div className="space-y-5 px-6 pb-12">
        <HomeChooser places={places} />
        <div className="h-[min(52vh,520px)] min-h-[280px]">
          <WorldMap focus={focus} onView={setView} />
        </div>

        {inView.length > 0 && (
          <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" role="list" aria-label="Places in this area">
            {inView.slice(0, 40).map((p) => (
              <button
                key={p.id}
                type="button"
                role="listitem"
                onClick={() => setFocus({ bounds: [p.lat, p.lon, p.lat, p.lon], key: Date.now() })}
                className="flex w-[200px] shrink-0 items-center gap-2.5 rounded-xl border border-line bg-surface p-2 text-left transition-colors hover:bg-surface-2"
                title={placeName(p)}
              >
                <span className="size-11 shrink-0 overflow-hidden rounded-lg bg-thumb">
                  {p.cover && <img src={mediaUrl(`media/thumb/${p.cover}?v=${p.cover_v ?? 1}`)} alt="" loading="lazy" className="size-full object-cover" />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-semibold">{p.name}</span>
                  <span className="block truncate text-xs text-fg-3">
                    {num(p.n)} · {[p.admin1, p.cc].filter(Boolean).join(', ')}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}

        <section>
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3">
            <h2 className="text-[17px] font-semibold tracking-tight">{title}</h2>
            <span className="text-[13px] text-fg-2">
              {media.data ? `${num(total)} ${total === 1 ? 'photo' : 'photos'}` : ''}
              {one ? ` · ${yearSpan(one.first, one.last)}` : ''}
            </span>
          </div>
          {media.data && media.data.items.length > 0 && <FlatGrid items={media.data.items} scope="places" />}
          {media.data && media.data.items.length === 0 && <p className="text-sm text-fg-2">No photos with a location in this area. Zoom out or pick a place above.</p>}
          {media.data && total > media.data.items.length && (
            <div className="mt-4 flex justify-center">
              <Button onClick={() => setMore({ key: boxKey, limit: limit + PAGE })}>Show more</Button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
