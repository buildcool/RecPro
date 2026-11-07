import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Bookmark, Compass, MapPin, Plus, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Button, EmptyState, Field, Modal, PageHeader, TextInput } from '../components/ui';
import { MemoryCard, useMemories } from '../features/memories/memories';
import { ModelSetupCard } from '../features/models/ModelSetup';
import type { PlacesResult } from '../features/places/places';
import { savedHref, useSavedSearches } from '../features/search/saved';
import { get, mediaUrl, post } from '../lib/api';
import { num } from '../lib/format';

type Lab = { id: number; key: string; name: string; grp: string; builtin: number; count: number; cover: number | null; cover_v: number | null };
type Group = { key: string; name: string; labels: Lab[] };

export function ExplorePage() {
  const { data, isLoading } = useQuery({ queryKey: ['explore'], queryFn: () => get<Group[]>('/api/explore') });
  const [creating, setCreating] = useState(false);
  const empty = !isLoading && (data ?? []).every((g) => g.labels.length === 0);
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="Explore"
        subtitle="What's in your photos: activities, places, things, documents and more, recognized on this PC."
        actions={
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
            Create a category
          </Button>
        }
      />
      <div className="space-y-8 px-6 pb-12">
        <ModelSetupCard need="siglip2" />
        <SavedRow />
        <MemoriesRow />
        <PlacesRow />
        {empty && (
          <EmptyState
            icon={<Compass className="size-6" />}
            title="Categories appear as photos are understood"
            body="Each photo is matched against activities, places, things, documents and screenshots. You can also create your own category by describing it."
          />
        )}
        {data
          ?.filter((g) => g.labels.length > 0 || g.key === 'custom')
          .map((g) => (
            <section key={g.key}>
              <h2 className="mb-3 text-[15px] font-semibold">{g.name}</h2>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
                {g.labels.map((l) => (
                  <Link key={l.id} to={`/explore/${l.id}`} className="group overflow-hidden rounded-2xl border border-line bg-surface transition-colors hover:border-line-strong">
                    <div className="aspect-[4/3] overflow-hidden bg-thumb">
                      {l.cover ? (
                        <img src={mediaUrl(`media/thumb/${l.cover}?v=${l.cover_v ?? 1}`)} alt="" loading="lazy" className="size-full object-cover transition-transform duration-300 group-hover:scale-105" />
                      ) : (
                        <div className="flex size-full items-center justify-center text-fg-3">
                          <Sparkles className="size-6" />
                        </div>
                      )}
                    </div>
                    <div className="px-3 py-2">
                      <div className="truncate text-sm font-semibold">{l.name}</div>
                      <div className="text-xs text-fg-3">{num(l.count)} items</div>
                    </div>
                  </Link>
                ))}
                {g.key === 'custom' && (
                  <button
                    type="button"
                    onClick={() => setCreating(true)}
                    className="flex min-h-[150px] flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line-strong text-fg-2 hover:border-accent hover:text-accent-text"
                  >
                    <Plus className="size-6" />
                    <span className="text-sm font-medium">New category</span>
                  </button>
                )}
              </div>
            </section>
          ))}
      </div>
      <CreateCategory open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

/** The towns with the most photos, and the way to the map. Hidden until a photo has a place. */
/** Searches you saved, as chips that run them again. Hidden until you save one. */
function SavedRow() {
  const { data } = useSavedSearches();
  if (!data?.length) return null;
  return (
    <section>
      <h2 className="mb-3 text-[15px] font-semibold">Saved searches</h2>
      <div className="flex flex-wrap gap-2">
        {data.map((s) => (
          <Link
            key={s.id}
            to={savedHref(s)}
            title={s.q}
            className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] transition-colors hover:bg-surface-2"
          >
            <Bookmark className="size-3.5 text-accent" />
            {s.name}
          </Link>
        ))}
      </div>
    </section>
  );
}

/** The latest trips and events, and the way to all of them. Hidden until there's one. */
function MemoriesRow() {
  const { data } = useMemories();
  const latest = [...(data?.trips ?? []), ...(data?.events ?? [])].sort((a, b) => b.start - a.start).slice(0, 6);
  if (!latest.length) return null;
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Trips and events</h2>
        <Link to="/memories" className="flex items-center gap-1 text-[13px] text-accent-text hover:underline">
          See all <ArrowRight className="size-3.5" />
        </Link>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        {latest.map((m) => (
          <MemoryCard key={m.key} m={m} />
        ))}
      </div>
    </section>
  );
}

function PlacesRow() {
  const { data } = useQuery({ queryKey: ['places', 'list'], queryFn: () => get<PlacesResult>('/api/places') });
  if (!data?.places.length) return null;
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Places</h2>
        <Link to="/places" className="flex items-center gap-1 text-[13px] text-accent-text hover:underline">
          See the map <ArrowRight className="size-3.5" />
        </Link>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        {data.places.slice(0, 6).map((p) => (
          <Link key={p.id} to={`/places?city=${p.id}`} className="group overflow-hidden rounded-2xl border border-line bg-surface transition-colors hover:border-line-strong">
            <div className="aspect-[4/3] overflow-hidden bg-thumb">
              {p.cover ? (
                <img src={mediaUrl(`media/thumb/${p.cover}?v=${p.cover_v ?? 1}`)} alt="" loading="lazy" className="size-full object-cover transition-transform duration-300 group-hover:scale-105" />
              ) : (
                <div className="flex size-full items-center justify-center text-fg-3">
                  <MapPin className="size-6" />
                </div>
              )}
            </div>
            <div className="px-3 py-2">
              <div className="truncate text-sm font-semibold">{p.name}</div>
              <div className="truncate text-xs text-fg-3">
                {num(p.n)} · {p.admin1 && p.admin1 !== p.name ? `${p.admin1}, ` : ''}
                {p.country}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function CreateCategory({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  return (
    <Modal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Create a category"
      description="Describe what you're looking for. RecPro scores every photo right away, asks you about unsure ones, and learns from your answers."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await post<{ id: number }>('/api/labels', { name, prompts: desc.split('\n') });
                toast.success(`Created ${name}`, { description: 'Matches appear in a few seconds.' });
                qc.invalidateQueries({ queryKey: ['explore'] });
                onClose();
                setName('');
                setDesc('');
                nav(`/explore/${r.id}`);
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name">
          <TextInput autoFocus placeholder="My bike" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Describe it (one way per line)" hint="For example: a red motorcycle · a person riding a motorbike on a highway">
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            rows={4}
            placeholder={'a red motorcycle\na person riding a motorbike'}
            className="w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
        </Field>
      </div>
    </Modal>
  );
}
