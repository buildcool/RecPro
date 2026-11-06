import { useQuery } from '@tanstack/react-query';
import { get } from './api';

export type Person = {
  id: number;
  name: string | null;
  cover_face_id: number | null;
  hidden: boolean;
  birthdate: string | null;
  kind: string;
  count: number;
  review: number;
};

export type PersonDetail = Person & {
  coverage: { found: number; to_check: number; expected_in_check: number; near_misses: number; percent: number };
  companions: { id: number; name: string; n: number; face_id: number | null }[];
};

export type Brief = { id: number; name: string | null; cover_face_id: number | null; faces: number[]; count: number };

export type ReviewFaces = {
  person: { id: number; name: string; cover_face_id: number | null } | null;
  known: number[];
  items: { face_id: number; media_id: number; score: number; probability: number; quality: number; private: boolean }[];
  remaining: number;
};

export type ReviewCounts = { faces: number; name: number; merge: number; total: number } & Record<string, number>;

export const useNamedPeople = () => useQuery({ queryKey: ['people', 'named'], queryFn: () => get<Person[]>('/api/people?named=1'), retry: false });

export const useUnnamedPeople = () =>
  useQuery({ queryKey: ['people', 'unnamed'], queryFn: () => get<Person[]>('/api/people?named=0&min_count=3'), retry: false });

export const useReviewCounts = () =>
  useQuery({ queryKey: ['review', 'counts'], queryFn: () => get<ReviewCounts>('/api/review/counts'), refetchInterval: 20_000, retry: false });

export type ModelInfo = {
  id: string;
  name: string;
  purpose: string;
  license: string;
  profiles: string[];
  size: number;
  installed: boolean;
  queued: boolean;
  progress: { state: string; bytes_done?: number; bytes_total?: number; file?: string; error?: string } | null;
};

export const useModels = () =>
  useQuery({
    queryKey: ['models'],
    queryFn: () => get<{ models: ModelInfo[]; device: { provider: string; name: string }; profile: string }>('/api/models'),
    refetchInterval: (q) => (q.state.data?.models.some((m) => m.queued || m.progress?.state === 'downloading') ? 1500 : 30_000),
  });
