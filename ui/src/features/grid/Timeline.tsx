import { useQuery } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { clsx } from 'clsx';
import { Check } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { get, qs } from '../../lib/api';
import { monthYear, num } from '../../lib/format';
import { useSelection } from '../../lib/selection';
import type { MediaItem } from '../../lib/types';
import { ROW_HEIGHT, estimateHeight, layoutItems } from './layout';
import { Thumb } from './Thumb';
import { useGridSelection } from './useGridSelection';
import { useZoom } from './zoom';

export type TimelineFilters = {
  folder_id?: number;
  rel_dir?: string;
  kind?: 'image' | 'video';
  person_id?: number;
  label_id?: number;
  private_only?: boolean;
};

type Month = { ym: string; count: number };
const HEADER = 48;
const PAD_X = 24;
const EMPTY = new Set<number>();

function monthTitle(ym: string): string {
  if (ym === '0000-00') return 'Unknown date';
  const [y, m] = ym.split('-').map(Number);
  return monthYear(new Date(y, m - 1, 15).getTime() / 1000);
}

function useWidth(ref: React.RefObject<HTMLElement | null>) {
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

export function Timeline({ filters, scope, header, empty }: { filters: TimelineFilters; scope: string; header?: ReactNode; empty?: ReactNode }) {
  const parentRef = useRef<HTMLDivElement>(null);
  const outer = useWidth(parentRef);
  const width = Math.max(0, outer - PAD_X * 2 - 28);
  const zoom = useZoom((s) => s.zoom);
  const rowHeight = ROW_HEIGHT[zoom];
  const key = JSON.stringify(filters);

  const timeline = useQuery({
    queryKey: ['timeline', filters],
    queryFn: () => get<{ months: Month[]; total: number }>(`/api/timeline${qs(filters)}`),
  });
  const ids = useQuery({
    queryKey: ['media', 'ids', filters],
    queryFn: () => get<number[]>(`/api/media/ids${qs(filters)}`),
  });
  const idsRef = useRef<number[]>([]);
  idsRef.current = ids.data ?? [];
  const orderedIds = useCallback(() => idsRef.current, []);
  const { onToggle, onActivate } = useGridSelection(scope, orderedIds);

  const months = timeline.data?.months ?? [];
  const hasHeader = !!header;
  const count = months.length + (hasHeader ? 1 : 0);

  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => parentRef.current,
    estimateSize: (i) => {
      if (hasHeader && i === 0) return 120;
      const m = months[i - (hasHeader ? 1 : 0)];
      return HEADER + estimateHeight(m?.count ?? 0, width, rowHeight) + 16;
    },
    overscan: 3,
    getItemKey: (i) => (hasHeader && i === 0 ? '__header' : `${key}:${months[i - (hasHeader ? 1 : 0)]?.ym}`),
  });

  useEffect(() => {
    virtualizer.measure();
  }, [width, rowHeight, virtualizer]);

  const years = useMemo(() => {
    const out: { year: string; index: number }[] = [];
    months.forEach((m, i) => {
      const y = m.ym.slice(0, 4);
      if (!out.length || out[out.length - 1].year !== y) out.push({ year: y === '0000' ? '?' : y, index: i + (hasHeader ? 1 : 0) });
    });
    return out;
  }, [months, hasHeader]);

  const isEmpty = timeline.isSuccess && months.length === 0;

  return (
    <div className="relative h-full">
      <div ref={parentRef} className="h-full overflow-y-auto" style={{ contain: 'strict' }}>
        {isEmpty ? (
          <>
            {header}
            {empty}
          </>
        ) : (
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {virtualizer.getVirtualItems().map((vi) => (
              <div
                key={vi.key}
                data-index={vi.index}
                ref={virtualizer.measureElement}
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${vi.start}px)` }}
              >
                {hasHeader && vi.index === 0 ? (
                  header
                ) : (
                  <MonthSection
                    month={months[vi.index - (hasHeader ? 1 : 0)]}
                    filters={filters}
                    width={width}
                    rowHeight={rowHeight}
                    scope={scope}
                    onToggle={onToggle}
                    onActivate={onActivate}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {years.length > 1 && (
        <div className="pointer-events-none absolute bottom-4 right-1 top-4 flex w-7 flex-col items-center justify-between">
          {years.map((y) => (
            <button
              key={y.year + y.index}
              type="button"
              onClick={() => virtualizer.scrollToIndex(y.index, { align: 'start' })}
              className="pointer-events-auto rounded px-0.5 text-[10px] font-medium text-fg-3 hover:bg-surface-2 hover:text-fg"
              title={`Jump to ${y.year}`}
            >
              {y.year === '?' ? '?' : `’${y.year.slice(2)}`}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function MonthSection({
  month,
  filters,
  width,
  rowHeight,
  scope,
  onToggle,
  onActivate,
}: {
  month: Month;
  filters: TimelineFilters;
  width: number;
  rowHeight: number;
  scope: string;
  onToggle: (item: MediaItem, e: React.MouseEvent) => void;
  onActivate: (item: MediaItem) => void;
}) {
  const { data: items } = useQuery({
    queryKey: ['media', 'month', month.ym, filters],
    queryFn: () => get<MediaItem[]>(`/api/media/month${qs({ ym: month.ym, ...filters })}`),
    staleTime: 15_000,
  });
  const layout = useMemo(() => (items ? layoutItems(items, width, rowHeight) : null), [items, width, rowHeight]);
  const selIds = useSelection((s) => (s.scope === scope ? s.ids : EMPTY));
  const selecting = selIds.size > 0;
  const allSelected = !!items?.length && items.every((i) => selIds.has(i.id));
  const height = layout?.height ?? estimateHeight(month.count, width, rowHeight);

  return (
    <section className="pb-4" style={{ paddingLeft: PAD_X, paddingRight: PAD_X + 28 }}>
      <div className="group/h flex h-12 items-center gap-2">
        <button
          type="button"
          aria-label={allSelected ? `Deselect ${monthTitle(month.ym)}` : `Select all of ${monthTitle(month.ym)}`}
          onClick={() => {
            if (!items) return;
            const sel = useSelection.getState();
            if (allSelected) sel.remove(items.map((i) => i.id));
            else sel.add(items.map((i) => i.id), scope);
          }}
          className={clsx(
            'flex size-5 items-center justify-center rounded-full border-2 transition-opacity',
            allSelected ? 'border-accent bg-accent text-white' : 'border-fg-3 text-transparent opacity-0 group-hover/h:opacity-100',
            selecting && 'opacity-100',
          )}
        >
          <Check className="size-3" strokeWidth={3} />
        </button>
        <h3 className="text-[15px] font-semibold">{monthTitle(month.ym)}</h3>
        <span className="text-[13px] text-fg-3">{num(month.count)}</span>
      </div>
      <div className="relative" style={{ height }}>
        {!layout && <div className="skeleton absolute inset-0 rounded-lg opacity-60" />}
        {layout &&
          items!.map((item, i) => (
            <Thumb
              key={item.id}
              item={item}
              box={layout.boxes[i]}
              selected={selIds.has(item.id)}
              selecting={selecting}
              onToggle={onToggle}
              onActivate={onActivate}
            />
          ))}
      </div>
    </section>
  );
}
