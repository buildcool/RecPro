import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Check, EyeOff, MessageCircleQuestion, Pencil, Wand2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { toast } from 'sonner';
import { Button, Progress, Tip } from '../components/ui';
import { Timeline } from '../features/grid/Timeline';
import { FaceAvatar } from '../features/people/FaceAvatar';
import { NameInput } from '../features/people/NameInput';
import { namePerson } from '../features/people/actions';
import { get, patch } from '../lib/api';
import { num } from '../lib/format';
import { type PersonDetail, speciesName } from '../lib/people';

export function PersonPage() {
  const { id } = useParams();
  const pid = Number(id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const { data: p } = useQuery({ queryKey: ['person', pid], queryFn: () => get<PersonDetail>(`/api/people/${pid}`), enabled: !!pid });

  const header = p && (
    <div className="px-6 pb-2 pt-5">
      <Link to="/people" className="mb-3 inline-flex items-center gap-1 text-[13px] text-fg-2 hover:text-fg">
        <ArrowLeft className="size-4" /> People
      </Link>
      <div className="flex flex-wrap items-center gap-5">
        <FaceAvatar faceId={p.cover_face_id} size={96} kind={p.kind} />
        <div className="min-w-0 flex-1">
          {editing || !p.name ? (
            <div className="max-w-xs">
              <NameInput
                autoFocus
                initial={p.name ?? ''}
                kind={p.kind}
                placeholder={p.kind === 'pet' ? "What's this pet called?" : 'Who is this?'}
                onSubmit={async ({ name, personId }) => {
                  const newId = await namePerson(pid, name, personId);
                  setEditing(false);
                  qc.invalidateQueries({ queryKey: ['people'] });
                  qc.invalidateQueries({ queryKey: ['person'] });
                  if (newId !== pid) nav(`/people/${newId}`, { replace: true });
                }}
              />
            </div>
          ) : (
            <button type="button" onClick={() => setEditing(true)} className="group flex items-center gap-2 text-left">
              <h1 className="text-[26px] font-semibold tracking-tight">{p.name}</h1>
              <Pencil className="size-4 text-fg-3 opacity-0 group-hover:opacity-100" />
            </button>
          )}
          <div className="mt-1 text-sm text-fg-2">
            {p.kind === 'pet' && `${speciesName(p.species)} · `}
            {num(p.count)} {p.kind === 'pet' ? 'photos' : 'photos and videos'}
            {p.review > 0 && ` · ${num(p.review)} to check`}
          </div>
          {p.name && (
            <Tip label={`How many of ${p.kind === 'pet' ? "this pet's" : "this person's"} photos RecPro estimates it has found. Answering the questions raises it.`}>
              <div className="mt-2 flex max-w-sm items-center gap-3">
                <Progress value={p.coverage.percent} tone={p.coverage.percent >= 97 ? 'ok' : 'accent'} />
                <span className="shrink-0 text-xs text-fg-2">≈ {p.coverage.percent.toFixed(0)}% found</span>
              </div>
            </Tip>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {p.review > 0 && (
            <Button
              icon={<MessageCircleQuestion className="size-4" />}
              onClick={() => nav(p.kind === 'pet' ? `/review?tab=pets&person=${pid}` : `/review?person=${pid}`)}
            >
              Check {num(p.review)}
            </Button>
          )}
          {p.name && (
            <Button variant="primary" icon={<Wand2 className="size-4" />} onClick={() => nav(`/find?person=${pid}`)}>
              Find and move
            </Button>
          )}
          <Button
            variant="ghost"
            icon={<EyeOff className="size-4" />}
            onClick={async () => {
              await patch(`/api/people/${pid}`, { hidden: true });
              toast.success(p.kind === 'pet' ? 'Hidden from Pets' : 'Hidden from People', { description: 'Their photos stay in your library.' });
              qc.invalidateQueries({ queryKey: ['people'] });
              nav('/people');
            }}
          >
            Hide
          </Button>
        </div>
      </div>
      {p.companions.length > 0 && (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <span className="text-[13px] text-fg-2">Often with</span>
          {p.companions.map((c) => (
            <Link key={c.id} to={`/people/${c.id}`} className="flex items-center gap-1.5 rounded-full bg-surface py-1 pl-1 pr-3 text-[13px] hover:bg-surface-2">
              <FaceAvatar faceId={c.face_id} size={24} />
              {c.name}
              <span className="text-fg-3">{c.n}</span>
            </Link>
          ))}
        </div>
      )}
      {p.name && p.coverage.to_check === 0 && p.coverage.percent >= 99 && (
        <p className="mt-3 flex items-center gap-1.5 text-[13px] text-ok">
          <Check className="size-4" /> Nothing left to check for {p.name}.
        </p>
      )}
    </div>
  );

  return <Timeline scope={`person-${pid}`} filters={{ person_id: pid }} header={header} />;
}
