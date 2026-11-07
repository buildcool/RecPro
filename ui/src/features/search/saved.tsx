import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bookmark, BookmarkCheck, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button, Field, Modal, TextInput } from '../../components/ui';
import { del, get, patch, post } from '../../lib/api';

/** A search you saved: it runs again each time, so new photos join it. */
export type SavedSearch = { id: number; name: string; q: string; overrides: Record<string, unknown> | null; created_at: number };

export const useSavedSearches = () => useQuery({ queryKey: ['searches'], queryFn: () => get<SavedSearch[]>('/api/searches') });

export const savedHref = (s: SavedSearch) => `/search?q=${encodeURIComponent(s.q)}&s=${s.id}`;

const same = (a: Record<string, unknown> | null | undefined, b: Record<string, unknown>) =>
  JSON.stringify(a ?? {}) === JSON.stringify(b ?? {});

/** The Save button on the search page, and its dialog: save, rename or remove. */
export function SaveSearch({ q, removed, onSaved }: { q: string; removed: Record<string, unknown>; onSaved: (s: SavedSearch) => void }) {
  const qc = useQueryClient();
  const { data } = useSavedSearches();
  const match = data?.find((s) => s.q === q && same(s.overrides, removed)) ?? null;
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setName(match?.name ?? q);
  }, [open, match?.name, q]);

  const done = () => {
    qc.invalidateQueries({ queryKey: ['searches'] });
    setOpen(false);
  };
  const save = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      if (match) {
        await patch(`/api/searches/${match.id}`, { name });
        toast.success('Renamed');
      } else {
        const s = await post<SavedSearch>('/api/searches', { name, q, overrides: Object.keys(removed).length ? removed : null });
        toast.success(`Saved as “${s.name}”. Find it in Explore and with Ctrl+K.`);
        onSaved(s);
      }
      done();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!match) return;
    await del(`/api/searches/${match.id}`);
    toast.success('No longer saved');
    done();
  };

  return (
    <>
      <Button
        icon={match ? <BookmarkCheck className="size-4 text-accent" /> : <Bookmark className="size-4" />}
        onClick={() => setOpen(true)}
        aria-label={match ? `Saved as ${match.name}` : 'Save this search'}
      >
        {match ? 'Saved' : 'Save search'}
      </Button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={match ? 'Saved search' : 'Save this search'}
        description="It runs again each time you open it, so photos you add later join it."
        footer={
          <>
            {match && (
              <Button variant="ghost" icon={<Trash2 className="size-4" />} className="mr-auto" onClick={() => void remove()}>
                Remove
              </Button>
            )}
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={() => void save()}>
              {match ? 'Rename' : 'Save'}
            </Button>
          </>
        }
      >
        <Field label="Name">
          <TextInput value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void save()} autoFocus maxLength={80} />
        </Field>
      </Modal>
    </>
  );
}
