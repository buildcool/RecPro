import { useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { Check, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ApiError, mediaUrl, post } from '../../lib/api';
import { num } from '../../lib/format';
import { type Kind, speciesName } from '../../lib/people';
import type { AnimalBox, FaceBox } from '../../lib/types';
import { namePerson } from '../people/actions';
import { NameInput } from '../people/NameInput';

/** A face or an animal in the photo, and who RecPro thinks it is. */
type Who = { id: number; kind: Kind; personId: number | null; name: string | null; state: string; label: string };
type Answer = { person_id: number; new?: boolean; count?: number; to_check?: number };

/** The people and pets in a photo. Click one to name it, or to say it isn't who RecPro thinks. */
export function WhoInPhoto({ mediaId, faces, animals }: { mediaId: number; faces: FaceBox[]; animals: AnimalBox[] }) {
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => setOpen(null), [mediaId]);
  const people: Who[] = faces.map((f) => ({ id: f.id, kind: 'human', personId: f.person_id, name: f.person_name, state: f.state, label: f.person_name ?? 'Unnamed' }));
  const pets: Who[] = animals.map((a) => ({
    id: a.id,
    kind: 'pet',
    personId: a.person_id,
    name: a.person_name,
    state: a.state,
    label: a.person_name ?? speciesName(a.species),
  }));
  return (
    <>
      <Section title="People" items={people} open={open} setOpen={setOpen} mediaId={mediaId} />
      <Section title="Pets" items={pets} open={open} setOpen={setOpen} mediaId={mediaId} />
    </>
  );
}

function Section({
  title,
  items,
  open,
  setOpen,
  mediaId,
}: {
  title: string;
  items: Who[];
  open: string | null;
  setOpen: (v: string | null) => void;
  mediaId: number;
}) {
  if (items.length === 0) return null;
  const current = items.find((w) => `${w.kind}:${w.id}` === open);
  return (
    <div className="mt-5">
      <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/50">{title}</div>
      <div className="flex flex-wrap gap-2">
        {items.map((w) => {
          const key = `${w.kind}:${w.id}`;
          const on = open === key;
          return (
            <button
              key={key}
              type="button"
              aria-expanded={on}
              title={w.name ? `${w.name}: confirm or correct` : `Name this ${w.kind === 'pet' ? 'pet' : 'person'}`}
              onClick={() => setOpen(on ? null : key)}
              className={clsx('flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-xs transition-colors', on ? 'bg-white/25' : 'bg-white/10 hover:bg-white/15')}
            >
              <img src={mediaUrl(`media/${w.kind === 'pet' ? 'animal' : 'face'}/${w.id}?size=64`)} alt="" className="size-6 rounded-full object-cover" />
              {w.label}
              {w.state === 'suggested' && <span className="text-[#e5a94a]">?</span>}
            </button>
          );
        })}
      </div>
      {current && <Editor key={`${current.kind}:${current.id}`} who={current} mediaId={mediaId} done={() => setOpen(null)} />}
    </div>
  );
}

function Editor({ who, mediaId, done }: { who: Who; mediaId: number; done: () => void }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const pet = who.kind === 'pet';
  const base = `/api/${pet ? 'animals' : 'faces'}/${who.id}`;
  const group = who.personId != null && !who.name; // one of a group nobody has named yet

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['media', 'detail', mediaId] });
    qc.invalidateQueries({ queryKey: ['people'] });
    qc.invalidateQueries({ queryKey: ['person'] });
    qc.invalidateQueries({ queryKey: ['review'] });
  };
  const undo = {
    label: 'Undo',
    onClick: () => {
      void post('/api/review/undo').then(refresh);
    },
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
      refresh();
      done();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const assign = (name: string, personId?: number) =>
    run(async () => {
      if (group) {
        // naming one of an unnamed group names the whole group (or adds it to someone named)
        await namePerson(who.personId!, name, personId);
        return;
      }
      const r = await post<Answer>(`${base}/assign`, personId ? { person_id: personId } : { name });
      const more = Math.max(0, (r.count ?? 1) - 1);
      const found = [
        more ? `In ${num(more)} more ${more === 1 ? 'photo' : 'photos'}` : null,
        r.to_check ? `${num(r.to_check)} to check in Review` : null,
      ].filter(Boolean);
      toast.success(r.new ? `Named ${name}` : `This is ${name}`, { description: found.join(' · ') || undefined, action: r.new ? undefined : undo });
    });
  const notThem = () =>
    run(async () => {
      await post(`${base}/not`, { person_id: who.personId });
      toast(`Not ${who.name}`, { description: "RecPro won't suggest it again.", action: undo });
    });

  const message = group
    ? `In a group of unnamed ${pet ? 'pets' : 'people'}. A name here names the whole group.`
    : who.name
      ? who.state === 'confirmed'
        ? `You said this is ${who.name}.`
        : `RecPro thinks this is ${who.name}${who.state === 'suggested' ? ', but isn’t sure' : ''}.`
      : pet
        ? 'Which pet is this? Name it once and RecPro looks for its other photos.'
        : 'Who is this? Name them once and RecPro looks for their other photos.';
  const btn = 'inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2.5 py-1.5 text-xs font-medium hover:bg-white/15 disabled:opacity-50';
  return (
    <div className="mt-3 rounded-xl bg-white/[0.06] p-3" aria-busy={busy}>
      <p className="mb-2 text-xs text-white/75">{message}</p>
      {who.name && who.personId != null && (
        <div className="mb-2 flex flex-wrap gap-2">
          {who.state !== 'confirmed' && (
            <button type="button" className={btn} disabled={busy} onClick={() => void assign(who.name!, who.personId!)}>
              <Check className="size-3.5" /> Yes, it’s {who.name}
            </button>
          )}
          <button type="button" className={btn} disabled={busy} onClick={() => void notThem()}>
            <X className="size-3.5" /> Not {who.name}
          </button>
        </div>
      )}
      <NameInput
        tone="dark"
        kind={who.kind}
        autoFocus={!who.name}
        placeholder={who.name ? (pet ? 'Another pet' : 'Someone else') : pet ? 'Name this pet' : 'Add a name'}
        onSubmit={({ name, personId }) => void assign(name, personId)}
      />
    </div>
  );
}
