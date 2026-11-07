import { useQuery } from '@tanstack/react-query';
import { CalendarHeart, Luggage } from 'lucide-react';
import { Link } from 'react-router';
import { get, mediaUrl } from '../../lib/api';
import { dateRange, num } from '../../lib/format';
import type { MediaItem } from '../../lib/types';

/** A trip (days away from home) or an event (a celebration), from /api/memories. */
export type Memory = {
  key: string;
  kind: 'trip' | 'event';
  name: string;
  start: number;
  end: number;
  days: number;
  n: number;
  cover: number | null;
  cover_v: number | null;
  towns?: { id: number; name: string; admin1: string | null; n: number }[];
  country?: string;
  label?: string;
};
export type Home = { id: number; name: string; admin1: string | null; country: string; chosen: boolean };
export type MemoriesResult = { home: Home | null; trips: Memory[]; events: Memory[] };
export type MemoryDay = { date: string; place: string | null; items: MediaItem[] };
export type MemoryDetail = { memory: Memory; days: MemoryDay[] };

export const useMemories = () => useQuery({ queryKey: ['memories', 'list'], queryFn: () => get<MemoriesResult>('/api/memories') });

export function MemoryCard({ m, className = '' }: { m: Memory; className?: string }) {
  const Icon = m.kind === 'trip' ? Luggage : CalendarHeart;
  return (
    <Link
      to={`/memories/${m.key}`}
      className={`group block overflow-hidden rounded-2xl border border-line bg-surface transition-colors hover:border-line-strong ${className}`}
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-thumb">
        {m.cover ? (
          <img src={mediaUrl(`media/thumb/${m.cover}?v=${m.cover_v ?? 1}`)} alt="" loading="lazy" className="size-full object-cover transition-transform duration-300 group-hover:scale-105" />
        ) : (
          <div className="flex size-full items-center justify-center text-fg-3">
            <Icon className="size-6" />
          </div>
        )}
        <span className="absolute left-2 top-2 flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[10.5px] font-medium text-white">
          <Icon className="size-3" />
          {m.kind === 'trip' ? (m.days === 1 ? 'Day trip' : `${m.days} days`) : 'Event'}
        </span>
      </div>
      <div className="px-3 py-2">
        <div className="truncate text-sm font-semibold">{m.name}</div>
        <div className="truncate text-xs text-fg-3">
          {dateRange(m.start, m.end)} · {num(m.n)}
        </div>
      </div>
    </Link>
  );
}
