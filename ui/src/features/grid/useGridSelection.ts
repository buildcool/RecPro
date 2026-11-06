import { type MouseEvent, useCallback } from 'react';
import { useSelection } from '../../lib/selection';
import type { MediaItem } from '../../lib/types';
import { useViewer } from '../viewer/viewerStore';

/** Click / Ctrl+click / Shift+click behaviour shared by every grid. */
export function useGridSelection(scope: string, orderedIds: () => number[], startAt?: () => Record<number, number>) {
  const onToggle = useCallback(
    (item: MediaItem, e: MouseEvent) => {
      const sel = useSelection.getState();
      if (e.shiftKey && sel.anchor != null && sel.scope === scope) {
        const ids = orderedIds();
        const a = ids.indexOf(sel.anchor);
        const b = ids.indexOf(item.id);
        if (a >= 0 && b >= 0) {
          const [lo, hi] = a < b ? [a, b] : [b, a];
          sel.add(ids.slice(lo, hi + 1), scope);
          return;
        }
      }
      sel.toggle(item.id, scope);
    },
    [scope, orderedIds],
  );

  const onActivate = useCallback(
    (item: MediaItem) => {
      const ids = orderedIds();
      const idx = Math.max(0, ids.indexOf(item.id));
      useViewer.getState().show(ids.length ? ids : [item.id], ids.length ? idx : 0, startAt?.());
    },
    [orderedIds, startAt],
  );

  return { onToggle, onActivate };
}
