import { create } from 'zustand';

type ViewerState = {
  open: boolean;
  ids: number[];
  index: number;
  /** videos: where to start playing (ms), e.g. where a search found the person */
  startAt: Record<number, number>;
  show(ids: number[], index: number, startAt?: Record<number, number>): void;
  go(delta: number): void;
  close(): void;
};

export const useViewer = create<ViewerState>((set, get) => ({
  open: false,
  ids: [],
  index: 0,
  startAt: {},
  show: (ids, index, startAt) => set({ open: true, ids, index, startAt: startAt ?? {} }),
  go: (delta) => {
    const { ids, index } = get();
    const next = Math.min(ids.length - 1, Math.max(0, index + delta));
    set({ index: next });
  },
  close: () => set({ open: false }),
}));

/** Start times of the videos in a result list. */
export function startTimes(items: { id: number; at_ms?: number }[]): Record<number, number> {
  const out: Record<number, number> = {};
  for (const it of items) if (it.at_ms != null) out[it.id] = it.at_ms;
  return out;
}
