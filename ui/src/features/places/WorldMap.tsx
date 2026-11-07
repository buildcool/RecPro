import { useQuery } from '@tanstack/react-query';
import { geoMercator, geoPath } from 'd3-geo';
import { select } from 'd3-selection';
import 'd3-transition';
import { type D3ZoomEvent, type ZoomBehavior, type ZoomTransform, zoom as d3zoom, zoomIdentity } from 'd3-zoom';
import { Minus, Plus, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { feature, mesh } from 'topojson-client';
import type { GeometryCollection, Topology } from 'topojson-specification';
// Natural Earth country outlines (public domain), shipped with the app: no map tiles are fetched
import worldUrl from 'world-atlas/countries-50m.json?url';
import { get, mediaUrl } from '../../lib/api';
import { num } from '../../lib/format';

/** [south, west, north, east] in degrees. */
export type Bounds = [number, number, number, number];
/** The area shown; `world` while the whole world fits. */
export type MapView = { s: number; w: number; n: number; e: number; world: boolean };
type Cluster = {
  lat: number;
  lon: number;
  n: number;
  cover: number | null;
  cover_v: number | null;
  name: string | null; // the town most of them are in
  locality: string | null; // the neighbourhood or village most of them are in
  towns: number;
  bounds: Bounds;
};
type Town = { id: number; name: string; lat: number; lon: number; pop: number };

// The map has its own fixed coordinates (the world 256 units wide, like web maps) and the zoom
// transform is the window onto them, so the panel changing width never moves what's in view.
const WORLD = 256;
const projection = geoMercator()
  .scale(WORLD / (2 * Math.PI))
  .translate([0, 0]);
const Y = (lat: number) => projection([0, lat])![1];
const FIRST = { n: 76, s: -56 }; // the first look leaves out Antarctica and the far north
const LIMITS: [[number, number], [number, number]] = [[-WORLD / 2, Y(85)], [WORLD / 2, Y(-85)]];
// zoom, as times closer than the whole world
const MAX_REL = 4096; // about 15 m a pixel: closer than any town needs
const POINT_REL = 512; // flying to a single place: the town fills the view
const FIT_REL = 1024; // flying to an area: never closer than this
const TOWN_REL = 3; // town names appear
const LABEL_REL = 4; // every dot gets its name
const CLOSE_REL = 128; // a dot is named by its neighbourhood too
const DOT_PX = 64; // photos closer than this on screen share a dot

let worldCache: Promise<Topology> | null = null;
const loadWorld = () => (worldCache ??= fetch(worldUrl).then((r) => r.json() as Promise<Topology>));

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const fitK = (w: number, h: number) => Math.max(0.1, Math.min((w - 16) / WORLD, (h - 16) / (Y(FIRST.s) - Y(FIRST.n))));
const wholeWorld = (w: number, h: number) =>
  zoomIdentity
    .translate(w / 2, h / 2)
    .scale(fitK(w, h))
    .translate(0, -(Y(FIRST.n) + Y(FIRST.s)) / 2);

export function WorldMap({ focus, onView }: { focus: { bounds: Bounds; key: number } | null; onView: (v: MapView) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const zoomer = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [t, setT] = useState<ZoomTransform | null>(null);
  const [settled, setSettled] = useState<ZoomTransform | null>(null);
  const [shapes, setShapes] = useState<{ land: GeoJSON.FeatureCollection; borders: GeoJSON.MultiLineString } | null>(null);
  const fit = size.w ? fitK(size.w, size.h) : 1;

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let live = true;
    void loadWorld().then((topo) => {
      if (!live) return;
      const countries = topo.objects.countries as GeometryCollection;
      setShapes({
        land: feature(topo, countries) as unknown as GeoJSON.FeatureCollection,
        borders: mesh(topo, countries, (a, b) => a !== b) as GeoJSON.MultiLineString,
      });
    });
    return () => {
      live = false;
    };
  }, []);

  // drawn once: zooming and resizing only move the window
  const paths = useMemo(() => {
    if (!shapes) return null;
    const p = geoPath(projection);
    return { land: p(shapes.land) ?? '', borders: p(shapes.borders) ?? '' };
  }, [shapes]);

  useEffect(() => {
    const el = svg.current;
    if (!el || !size.w) return;
    const k0 = fitK(size.w, size.h);
    const z = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([k0, k0 * MAX_REL])
      .extent([[0, 0], [size.w, size.h]])
      .translateExtent(LIMITS)
      .on('zoom', (e: D3ZoomEvent<SVGSVGElement, unknown>) => setT(e.transform))
      .on('end', (e: D3ZoomEvent<SVGSVGElement, unknown>) => setSettled(e.transform));
    zoomer.current = z;
    const first = !(el as unknown as { __zoom?: unknown }).__zoom;
    select(el).call(z);
    if (first) select(el).call(z.transform, wholeWorld(size.w, size.h)); // the first look; later resizes keep the view
    return () => {
      select(el).on('.zoom', null);
    };
  }, [size]);

  const viewOf = useCallback(
    (tr: ZoomTransform | null): MapView | null => {
      if (!tr || !size.w) return null;
      const [x0, y0] = tr.invert([0, 0]);
      const [x1, y1] = tr.invert([size.w, size.h]);
      const lon = (x: number) => clamp((x / WORLD) * 360, -180, 180);
      const lat = (y: number) => clamp(projection.invert!([0, y])![1], -85, 85);
      return { w: lon(x0), e: lon(x1), n: lat(y0), s: lat(y1), world: tr.k <= fitK(size.w, size.h) * 1.05 };
    },
    [size],
  );

  useEffect(() => {
    const v = viewOf(settled);
    if (v) onView(v);
  }, [settled, viewOf, onView]);

  const go = useCallback(
    (target: ZoomTransform, ms: number) => {
      const el = svg.current;
      if (!el || !zoomer.current) return;
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      select(el).transition().duration(reduce ? 0 : ms).call(zoomer.current.transform, target);
    },
    [],
  );

  const fly = useCallback(
    (b: Bounds, ms = 750) => {
      if (!size.w) return;
      const p0 = projection([b[1], b[2]])!;
      const p1 = projection([b[3], b[0]])!;
      const dx = Math.abs(p1[0] - p0[0]);
      const dy = Math.abs(p1[1] - p0[1]);
      const k0 = fitK(size.w, size.h);
      const k =
        dx < 1e-9 && dy < 1e-9
          ? k0 * POINT_REL
          : clamp(Math.min((0.6 * size.w) / Math.max(dx, 1e-9), (0.6 * size.h) / Math.max(dy, 1e-9)), k0, k0 * FIT_REL);
      go(zoomIdentity.translate(size.w / 2, size.h / 2).scale(k).translate(-(p0[0] + p1[0]) / 2, -(p0[1] + p1[1]) / 2), ms);
    },
    [size, go],
  );

  // a new place asked for, or the map just got its size: go there. Not on every resize, which
  // would undo where you've panned to.
  const ready = size.w > 0;
  useEffect(() => {
    if (focus && ready) fly(focus.bounds);
  }, [focus, ready]);

  const rel = settled ? settled.k / fit : 1;
  // dots: photos grouped on a grid about DOT_PX wide on screen, for the area shown (with a margin)
  const level = settled ? clamp(Math.ceil(Math.log2((WORLD * settled.k) / DOT_PX)), 0, 22) : 0;
  const cell = 360 / 2 ** level;
  const v = viewOf(settled);
  const pad = cell * 4;
  const area = v
    ? [
        clamp(Math.floor((v.s - pad) / pad) * pad, -90, 90),
        clamp(Math.floor((v.w - pad) / pad) * pad, -180, 180),
        clamp(Math.ceil((v.n + pad) / pad) * pad, -90, 90),
        clamp(Math.ceil((v.e + pad) / pad) * pad, -180, 180),
      ]
    : null;
  const { data } = useQuery({
    queryKey: ['places', 'clusters', cell, area],
    queryFn: () => get<{ clusters: Cluster[] }>(`/api/places/clusters?cell=${cell}&s=${area![0]}&w=${area![1]}&n=${area![2]}&e=${area![3]}`),
    enabled: !!area,
    placeholderData: (prev) => prev,
  });

  // the biggest towns in view, for orientation once the country outlines alone don't say where you are
  const near = v && rel >= TOWN_REL ? [v.s, v.w, v.n, v.e].map((x) => x.toFixed(3)) : null;
  const { data: towns } = useQuery({
    queryKey: ['places', 'towns', near?.join(',')],
    queryFn: () => get<{ towns: Town[] }>(`/api/places/towns?s=${near![0]}&w=${near![1]}&n=${near![2]}&e=${near![3]}&limit=60`),
    enabled: !!near,
    placeholderData: (prev) => prev,
    staleTime: Infinity,
  });
  const labels = useMemo(() => {
    if (!t || !towns || rel < TOWN_REL) return [];
    // photo dots first; a town name goes where it touches nothing already placed
    const taken: [number, number, number, number][] = [];
    for (const c of data?.clusters ?? []) {
      const [x, y] = t.apply(projection([c.lon, c.lat])!);
      taken.push([x - 32, y - 32, x + 32, y + 50]);
    }
    const out: (Town & { x: number; y: number })[] = [];
    for (const tw of towns.towns) {
      const [x, y] = t.apply(projection([tw.lon, tw.lat])!);
      if (x < 4 || y < 10 || x > size.w - 40 || y > size.h - 24) continue;
      const b: [number, number, number, number] = [x - 4, y - 9, x + 10 + tw.name.length * 6.2, y + 7];
      if (taken.some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1])) continue;
      taken.push(b);
      out.push({ ...tw, x, y });
      if (out.length >= 24) break;
    }
    return out;
  }, [towns, rel, data, t, size]);

  const step = (by: number) => {
    if (svg.current && zoomer.current) select(svg.current).transition().duration(250).call(zoomer.current.scaleBy, by);
  };

  return (
    <div ref={box} className="relative h-full w-full overflow-hidden rounded-2xl border border-line bg-[var(--map-water)]">
      <svg ref={svg} width={size.w} height={size.h} className="block touch-none select-none" role="group" aria-label="Map of where your photos were taken">
        <defs>
          <clipPath id="rp-dot" clipPathUnits="objectBoundingBox">
            <circle cx="0.5" cy="0.5" r="0.5" />
          </clipPath>
        </defs>
        {paths && t && (
          <g transform={t.toString()}>
            <path d={paths.land} fill="var(--map-land)" />
            <path d={paths.borders} fill="none" stroke="var(--map-border)" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
          </g>
        )}
        {labels.map((tw) => (
          <g key={tw.id} transform={`translate(${tw.x},${tw.y})`} className="pointer-events-none" aria-hidden>
            <circle r={2.5} fill="var(--fg-3)" />
            <text x={6} y={3.5} className="map-town">
              {tw.name}
            </text>
          </g>
        ))}
        {t &&
          data?.clusters.map((c) => {
            const [x, y] = t.apply(projection([c.lon, c.lat])!);
            if (x < -60 || y < -60 || x > size.w + 60 || y > size.h + 60) return null;
            const r = clamp(14 + 5 * Math.log10(c.n), 14, 30);
            const label = !c.name
              ? null
              : c.towns > 1
                ? `${c.name} +${c.towns - 1}`
                : rel >= CLOSE_REL && c.locality && c.locality !== c.name
                  ? `${c.name} · ${c.locality}`
                  : c.name;
            const digits = Math.max(0, String(c.n > 999 ? `${Math.round(c.n / 100) / 10}k` : c.n).length - 2);
            return (
              <g
                key={`${c.bounds.join(',')}`}
                transform={`translate(${x},${y})`}
                className="cursor-pointer"
                role="button"
                tabIndex={0}
                aria-label={`${label ?? 'Photos'}: ${c.n} ${c.n === 1 ? 'photo' : 'photos'}. Zoom in`}
                onClick={() => fly(c.bounds)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fly(c.bounds)}
              >
                <circle r={r + 2.5} fill="var(--surface)" className="drop-shadow" />
                {c.cover ? (
                  <image
                    href={mediaUrl(`media/thumb/${c.cover}?v=${c.cover_v ?? 1}`)}
                    x={-r}
                    y={-r}
                    width={2 * r}
                    height={2 * r}
                    preserveAspectRatio="xMidYMid slice"
                    clipPath="url(#rp-dot)"
                  />
                ) : (
                  <circle r={r} fill="var(--accent)" />
                )}
                {c.n > 1 && (
                  <g transform={`translate(${r * 0.72},${-r * 0.72})`}>
                    <rect x={-11} y={-9} width={22 + digits * 6} height={18} rx={9} fill="var(--accent)" />
                    <text x={(digits * 6) / 2} y={4} textAnchor="middle" fontSize={10.5} fontWeight={700} fill="var(--accent-fg)">
                      {c.n > 999 ? `${Math.round(c.n / 100) / 10}k` : c.n}
                    </text>
                  </g>
                )}
                {label && (rel >= LABEL_REL || (data?.clusters.length ?? 0) <= 12) && (
                  <text y={r + 15} textAnchor="middle" className="map-label">
                    {label}
                  </text>
                )}
              </g>
            );
          })}
      </svg>
      <div className="absolute bottom-3 right-3 flex flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-sm">
        <button type="button" onClick={() => step(2)} className="flex size-8 items-center justify-center hover:bg-surface-2" aria-label="Zoom in">
          <Plus className="size-4" />
        </button>
        <button type="button" onClick={() => step(0.5)} className="flex size-8 items-center justify-center border-t border-line hover:bg-surface-2" aria-label="Zoom out">
          <Minus className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => size.w && go(wholeWorld(size.w, size.h), 500)}
          className="flex size-8 items-center justify-center border-t border-line hover:bg-surface-2"
          aria-label="Whole world"
        >
          <RotateCcw className="size-3.5" />
        </button>
      </div>
      <div className="pointer-events-none absolute bottom-2 left-3 text-[10px] text-fg-2">Map: Natural Earth · Place names: GeoNames · on this PC</div>
      {!paths && <div className="absolute inset-0 flex items-center justify-center text-sm text-fg-3">Drawing the map…</div>}
      {data && data.clusters.length === 0 && paths && (
        <div className="pointer-events-none absolute inset-x-0 top-3 text-center text-xs text-fg-3">No photos with a location in this area</div>
      )}
      <span className="sr-only">{data ? `${num(data.clusters.reduce((a, c) => a + c.n, 0))} photos on the map` : ''}</span>
    </div>
  );
}
