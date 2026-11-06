import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSelection } from '../../lib/selection';
import type { MediaItem } from '../../lib/types';
import { ROW_HEIGHT, layoutItems } from './layout';
import { Thumb } from './Thumb';
import { useGridSelection } from './useGridSelection';
import { useZoom } from './zoom';

const EMPTY = new Set<number>();

/** Justified grid for an explicit list (search results, a category's "maybe" items). */
export function FlatGrid({ items, scope, badge }: { items: MediaItem[]; scope: string; badge?: (it: MediaItem) => React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const zoom = useZoom((s) => s.zoom);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const layout = useMemo(() => layoutItems(items, width, ROW_HEIGHT[zoom]), [items, width, zoom]);
  const ids = useMemo(() => items.map((i) => i.id), [items]);
  const orderedIds = useCallback(() => ids, [ids]);
  const { onToggle, onActivate } = useGridSelection(scope, orderedIds);
  const sel = useSelection((s) => (s.scope === scope ? s.ids : EMPTY));
  return (
    <div ref={ref} className="relative w-full" style={{ height: layout.height }}>
      {items.map((it, i) =>
        layout.boxes[i] ? (
          <Thumb
            key={it.id}
            item={it}
            box={layout.boxes[i]}
            selected={sel.has(it.id)}
            selecting={sel.size > 0}
            onToggle={onToggle}
            onActivate={onActivate}
            badge={badge?.(it)}
          />
        ) : null,
      )}
    </div>
  );
}
