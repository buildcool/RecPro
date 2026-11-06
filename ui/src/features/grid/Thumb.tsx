import { clsx } from 'clsx';
import { Check, EyeOff, ImageOff, Lock, Play, Users } from 'lucide-react';
import { memo, type MouseEvent, useRef, useState } from 'react';
import { mediaUrl } from '../../lib/api';
import { bridge } from '../../lib/bridge';
import { duration } from '../../lib/format';
import { useSelection } from '../../lib/selection';
import type { MediaItem } from '../../lib/types';

type Props = {
  item: MediaItem;
  box: { left: number; top: number; width: number; height: number };
  selected: boolean;
  selecting: boolean;
  onActivate: (item: MediaItem, e: MouseEvent) => void;
  onToggle: (item: MediaItem, e: MouseEvent) => void;
  badge?: React.ReactNode;
};

export const Thumb = memo(function Thumb({ item, box, selected, selecting, onActivate, onToggle, badge }: Props) {
  const [peek, setPeek] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  // Private items stay blurred; press and hold to peek (only possible while Private is unlocked)
  const hidden = (item.priv && !peek) || item.chk;
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${item.kind === 'video' ? 'Video' : 'Photo'}${selected ? ', selected' : ''}`}
      aria-pressed={selected}
      className={clsx(
        'group absolute cursor-pointer overflow-hidden rounded-[6px] bg-thumb outline-none focus-visible:ring-2 focus-visible:ring-accent',
      )}
      style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
      onClick={(e) => (selecting || e.ctrlKey || e.metaKey || e.shiftKey ? onToggle(item, e) : onActivate(item, e))}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onActivate(item, e as unknown as MouseEvent);
        if (e.key === ' ') {
          e.preventDefault();
          onToggle(item, e as unknown as MouseEvent);
        }
      }}
      onPointerDown={(e) => {
        if (!item.priv || e.button !== 0) return;
        timer.current = window.setTimeout(() => setPeek(true), 250);
      }}
      onPointerUp={() => {
        window.clearTimeout(timer.current);
        setPeek(false);
      }}
      onPointerLeave={() => {
        window.clearTimeout(timer.current);
        setPeek(false);
      }}
      draggable={!!bridge && !item.priv}
      onDragStart={(e) => {
        if (!bridge) return;
        e.preventDefault();
        const sel = useSelection.getState().ids;
        const ids = sel.has(item.id) ? [...sel] : [item.id];
        bridge.startDragIds(ids);
      }}
    >
      {item.err ? (
        <div className="flex size-full flex-col items-center justify-center gap-1 text-fg-3">
          <ImageOff className="size-5" />
          <span className="text-[11px]">Can't open</span>
        </div>
      ) : (
        <img
          src={mediaUrl(`media/thumb/${item.id}?v=${item.v}`)}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          className={clsx(
            'size-full object-cover transition-transform duration-200',
            selected && 'scale-[0.92] rounded-[4px]',
            hidden && 'blur-private',
          )}
        />
      )}
      {selected && <div className="pointer-events-none absolute inset-0 rounded-[6px] ring-[3px] ring-inset ring-accent" />}
      {/* selection checkbox */}
      <button
        type="button"
        aria-label={selected ? 'Deselect' : 'Select'}
        onClick={(e) => {
          e.stopPropagation();
          onToggle(item, e);
        }}
        className={clsx(
          'absolute left-1.5 top-1.5 flex size-6 items-center justify-center rounded-full border-2 transition-opacity',
          selected ? 'border-accent bg-accent text-white opacity-100' : 'border-white/90 bg-black/20 text-transparent opacity-0 group-hover:opacity-100',
          selecting && !selected && 'opacity-100',
        )}
      >
        <Check className="size-3.5" strokeWidth={3} />
      </button>
      {item.kind === 'video' && (
        <span className="pointer-events-none absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] font-medium text-white">
          <Play className="size-3 fill-white" />
          {duration(item.dur)}
        </span>
      )}
      {item.faces > 1 && !hidden && (
        <span className="pointer-events-none absolute bottom-1.5 left-1.5 flex items-center gap-1 rounded-md bg-black/50 px-1.5 py-0.5 text-[11px] text-white opacity-0 group-hover:opacity-100">
          <Users className="size-3" />
          {item.faces}
        </span>
      )}
      {item.priv && (
        <span className="pointer-events-none absolute right-1.5 top-1.5 rounded-md bg-private/90 p-1 text-white">
          <Lock className="size-3" />
        </span>
      )}
      {item.chk && !item.priv && (
        <span className="pointer-events-none absolute inset-x-0 bottom-1.5 mx-auto flex w-fit items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] text-white">
          <EyeOff className="size-3" /> Checking…
        </span>
      )}
      {badge}
    </div>
  );
});
