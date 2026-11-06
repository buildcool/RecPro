import { create } from 'zustand';

/** Global entry point for the copy/move flow (implemented in M1's CopyDialog). */
type CopyFlowState = {
  open: boolean;
  mediaIds: number[];
  mode: 'copy' | 'move';
  context: { personIds?: number[]; title?: string } | null;
  start(ids: number[], mode: 'copy' | 'move', context?: CopyFlowState['context']): void;
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
