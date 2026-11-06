import { create } from 'zustand';

/** Global multi-select used by grids and the bottom action bar. */
type SelectionState = {
  ids: Set<number>;
  anchor: number | null;
  scope: string | null; // which view owns the selection
  toggle(id: number, scope: string): void;
  set(ids: number[], scope: string): void;
  add(ids: number[], scope: string): void;
  remove(ids: number[]): void;
  clear(): void;
  setAnchor(id: number | null): void;
};

export const useSelection = create<SelectionState>((set) => ({
  ids: new Set(),
  anchor: null,
  scope: null,
  toggle: (id, scope) =>
    set((s) => {
      const ids = s.scope === scope ? new Set(s.ids) : new Set<number>();
      if (ids.has(id)) ids.delete(id);
      else ids.add(id);
      return { ids, scope, anchor: id };
    }),
  set: (ids, scope) => set({ ids: new Set(ids), scope }),
  add: (ids, scope) =>
    set((s) => {
      const next = s.scope === scope ? new Set(s.ids) : new Set<number>();
      ids.forEach((i) => next.add(i));
      return { ids: next, scope };
    }),
  remove: (ids) =>
    set((s) => {
      const next = new Set(s.ids);
      ids.forEach((i) => next.delete(i));
      return { ids: next };
    }),
  clear: () => set({ ids: new Set(), anchor: null }),
  setAnchor: (id) => set({ anchor: id }),
}));
