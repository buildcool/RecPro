import { useQueryClient } from '@tanstack/react-query';
import { EyeOff, MessageCircleQuestion, PawPrint, Search, Users, Wand2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Badge, Button, EmptyState, PageHeader, TextInput } from '../components/ui';
import { FaceAvatar } from '../features/people/FaceAvatar';
import { NameInput } from '../features/people/NameInput';
import { namePerson } from '../features/people/actions';
import { ModelSetupCard } from '../features/models/ModelSetup';
import { num } from '../lib/format';
import { type Person, speciesName, useNamedPeople, useNamedPets, useUnnamedPeople, useUnnamedPets } from '../lib/people';

export function PeoplePage() {
  const named = useNamedPeople();
  const unnamed = useUnnamedPeople();
  const pets = useNamedPets();
  const unnamedPets = useUnnamedPets();
  const [q, setQ] = useState('');
  const nav = useNavigate();
  const needle = q.trim().toLowerCase();
  const match = (p: Person) => !needle || !!p.name?.toLowerCase().includes(needle);
  const filtered = (named.data ?? []).filter(match);
  const filteredPets = (pets.data ?? []).filter(match);
  const toReview = [...(named.data ?? []), ...(pets.data ?? [])].reduce((a, p) => a + p.review, 0);
  const anyPets = filteredPets.length + (unnamedPets.data?.length ?? 0) > 0;

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        title="People"
        subtitle="Faces are grouped automatically on this PC. Name a group to search by that person."
        actions={
          <>
            <div className="relative w-56">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-fg-3" />
              <TextInput className="pl-8" placeholder="Search names" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {toReview > 0 && (
              <Button icon={<MessageCircleQuestion className="size-4" />} onClick={() => nav('/review')}>
                Check {num(toReview)} suggestions
              </Button>
            )}
            <Button variant="primary" icon={<Wand2 className="size-4" />} onClick={() => nav('/find')}>
              Find and move
            </Button>
          </>
        }
      />
      <div className="space-y-8 px-6 pb-12">
        <ModelSetupCard need="faces" />
        {named.isSuccess && filtered.length === 0 && (unnamed.data?.length ?? 0) === 0 && !anyPets && (
          <EmptyState
            icon={<Users className="size-6" />}
            title="No people yet"
            body="As your photos are analyzed, faces that belong together are grouped here. Give a group a name and RecPro finds that person everywhere."
          />
        )}
        {filtered.length > 0 && (
          <section>
            <h2 className="mb-3 text-[15px] font-semibold">Named</h2>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-4">
              {filtered.map((p) => (
                <PersonCard key={p.id} p={p} />
              ))}
            </div>
          </section>
        )}
        {(unnamed.data?.length ?? 0) > 0 && (
          <section>
            <div className="mb-3 flex items-baseline gap-2">
              <h2 className="text-[15px] font-semibold">Who are these people?</h2>
              <span className="text-[13px] text-fg-2">Name a group, or type an existing name to add them to that person.</span>
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
              {unnamed.data!.map((p) => (
                <UnnamedCard key={p.id} p={p} />
              ))}
            </div>
          </section>
        )}
        <section aria-labelledby="pets-heading">
          <div className="mb-3 flex flex-wrap items-baseline gap-2">
            <h2 id="pets-heading" className="flex items-center gap-1.5 text-[15px] font-semibold">
              <PawPrint className="size-4" /> Pets
            </h2>
            <span className="text-[13px] text-fg-2">Dogs, cats, rabbits and parrots are told apart by how they look. Name one to find all its photos.</span>
          </div>
          <ModelSetupCard need="pets" />
          {filteredPets.length > 0 && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-4">
              {filteredPets.map((p) => (
                <PersonCard key={p.id} p={p} />
              ))}
            </div>
          )}
          {(unnamedPets.data?.length ?? 0) > 0 && (
            <>
              <h3 className="mb-3 mt-6 text-[14px] font-semibold">Whose pet is this?</h3>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
                {unnamedPets.data!.map((p) => (
                  <UnnamedCard key={p.id} p={p} />
                ))}
              </div>
            </>
          )}
          {pets.isSuccess && !anyPets && (
            <p className="text-[13px] text-fg-3">No pets found yet. The same animal seen in three or more photos shows up here.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function PersonCard({ p }: { p: Person }) {
  return (
    <Link to={`/people/${p.id}`} className="group flex flex-col items-center rounded-2xl p-3 text-center transition-colors hover:bg-surface">
      <div className="relative">
        <FaceAvatar faceId={p.cover_face_id} size={104} kind={p.kind} className="transition-transform group-hover:scale-[1.03]" />
        {p.review > 0 && (
          <span className="absolute -right-1 top-0">
            <Badge tone="warn">{num(p.review)}?</Badge>
          </span>
        )}
      </div>
      <div className="mt-2 w-full truncate text-sm font-semibold">{p.name}</div>
      <div className="text-xs text-fg-3">
        {p.kind === 'pet' ? `${speciesName(p.species)} · ` : ''}
        {num(p.count)} photos
      </div>
    </Link>
  );
}

function UnnamedCard({ p }: { p: Person }) {
  const qc = useQueryClient();
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-line bg-surface p-3">
      <Link to={`/people/${p.id}`} className="flex flex-col items-center gap-1">
        <FaceAvatar faceId={p.cover_face_id} size={88} kind={p.kind} />
        <span className="text-xs text-fg-3">
          {p.kind === 'pet' ? `${speciesName(p.species)} · ` : ''}
          {num(p.count)} photos
        </span>
      </Link>
      <NameInput
        className="w-full"
        kind={p.kind}
        placeholder={p.kind === 'pet' ? 'Name this pet' : undefined}
        onSubmit={async ({ name, personId }) => {
          await namePerson(p.id, name, personId);
          qc.invalidateQueries({ queryKey: ['people'] });
          qc.invalidateQueries({ queryKey: ['review'] });
        }}
      />
      <button
        type="button"
        className="flex items-center gap-1 text-xs text-fg-3 hover:text-fg"
        onClick={async () => {
          const { patch } = await import('../lib/api');
          await patch(`/api/people/${p.id}`, { hidden: true });
          qc.invalidateQueries({ queryKey: ['people'] });
        }}
      >
        <EyeOff className="size-3.5" /> {p.kind === 'pet' ? 'Hide (not a pet of yours)' : 'Hide (strangers, posters…)'}
      </button>
    </div>
  );
}
