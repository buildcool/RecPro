import { create } from 'zustand';

/** Global entry point for the copy/move dialog. */
export type CopyContext = {
  title?: string;
  personIds?: number[];
  /** media id -> person name, enables the "By person" folder layout */
  personByMedia?: Record<number, string>;
} | null;

type CopyFlowState = {
  open: boolean;
  mediaIds: number[];
  mode: 'copy' | 'move';
  context: CopyContext;
  start(ids: number[], mode: 'copy' | 'move', context?: CopyContext): void;
  close(): void;
};

export const useCopyFlow = create<CopyFlowState>((set) => ({
  open: false,
  mediaIds: [],
  mode: 'copy',
  context: null,
  start: (mediaIds, mode, context = null) => set({ open: true, mediaIds, mode, context }),
  close: () => set({ open: false }),
}));
