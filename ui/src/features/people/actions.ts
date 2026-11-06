import { toast } from 'sonner';
import { ApiError, patch, post } from '../../lib/api';

/** Names a person/group. Typing an existing name (or picking it) merges into that person. */
export async function namePerson(personId: number, name: string, existingId?: number): Promise<number> {
  if (existingId && existingId !== personId) {
    await post(`/api/people/${personId}/merge`, { into: existingId });
    toast.success(`Added to ${name}`);
    return existingId;
  }
  try {
    const r = await patch<{ id: number; merged: boolean }>(`/api/people/${personId}`, { name });
    toast.success(`Named ${name}`);
    return r.id;
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const r = await patch<{ id: number; merged: boolean }>(`/api/people/${personId}`, { name, merge_if_exists: true });
      toast.success(`Added to ${name}`);
      return r.id;
    }
    toast.error((e as Error).message);
    throw e;
  }
}

export async function answerFaces(personId: number, yes: number[], no: number[]) {
  return post<{ settled: number; remaining: number }>('/api/review/faces/answer', { person_id: personId, yes, no });
}
