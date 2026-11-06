import { create } from 'zustand';

type ViewerState = {
  open: boolean;
  ids: number[];
  index: number;
  show(ids: number[], index: number): void;
  go(delta: number): void;
  close(): void;
};

export const useViewer = create<ViewerState>((set, get) => ({
  open: false,
  ids: [],
  index: 0,
  show: (ids, index) => set({ open: true, ids, index }),
  go: (delta) => {
    const { ids, index } = get();
    const next = Math.min(ids.length - 1, Math.max(0, index + delta));
    set({ index: next });
  },
  close: () => set({ open: false }),
}));
