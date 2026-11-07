import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, patch } from './api';
import type { Folder, Health, Settings, Stats } from './types';

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: () => get<Health>('/api/health'), staleTime: 30_000 });

export const useSettings = () => useQuery({ queryKey: ['settings'], queryFn: () => get<Settings>('/api/settings') });

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => patch<Settings>('/api/settings', values),
    onSuccess: (s) => qc.setQueryData(['settings'], s),
  });
}

export const useFolders = () =>
  useQuery({ queryKey: ['folders'], queryFn: () => get<Folder[]>('/api/folders'), refetchInterval: 10_000 });

export const useStats = () => useQuery({ queryKey: ['stats'], queryFn: () => get<Stats>('/api/stats'), refetchInterval: 15_000 });

export type Op = {
  id: number;
  kind: 'copy' | 'move' | 'cleanup';
  status: 'running' | 'paused' | 'done' | 'failed' | 'cancelled' | 'undone';
  title: string | null;
  dest: string;
  structure: string;
  conflict: string;
  removal: 'bin' | 'recycle' | 'keep' | null;
  created_at: number;
  finished_at: number | null;
  total: number;
  done: number;
  failed: number;
  bytes_total: number;
  bytes_done: number;
  counts: Record<string, number>;
  removable: number;
  rate?: number | null;
  error?: string | null;
};

export const useOps = () => useQuery({ queryKey: ['ops'], queryFn: () => get<Op[]>('/api/ops') });

export type CleanupKind = 'exact' | 'copies' | 'bursts' | 'dark' | 'blurry' | 'forwards';
/** What each kind of cleanup would free: groups (duplicates, copies, similar shots) or single files. */
export type CleanupSummary = Record<CleanupKind, { groups?: number; files: number; bytes: number; greetings?: number }> & {
  total: { files: number; bytes: number }; // each file once, even when it's in two lists
};

export const useCleanupSummary = () =>
  useQuery({ queryKey: ['cleanup'], queryFn: () => get<CleanupSummary>('/api/cleanup'), staleTime: 30_000, retry: false });
