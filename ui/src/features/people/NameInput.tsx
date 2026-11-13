import { clsx } from 'clsx';
import { Check } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { type Kind, useNamedPeople, useNamedPets } from '../../lib/people';
import { FaceAvatar } from './FaceAvatar';

/** Text input that suggests existing names; picking one means "same person" (or with kind="pet", same pet). */
export function NameInput({
  onSubmit,
  placeholder = 'Add a name',
  autoFocus,
  initial = '',
  className,
  kind = 'human',
  tone = 'default',
}: {
  onSubmit: (value: { name: string; personId?: number }) => void;
  placeholder?: string;
  autoFocus?: boolean;
  initial?: string;
  className?: string;
  kind?: Kind;
  tone?: 'default' | 'dark'; // dark: on the photo viewer's panel, dark in either theme
}) {
  const dark = tone === 'dark';
  const humans = useNamedPeople();
  const pets = useNamedPets();
  const people = (kind === 'pet' ? pets : humans).data;
  const [v, setV] = useState(initial);
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  const matches = useMemo(() => {
    const q = v.trim().toLowerCase();
    if (!q) return [];
    return (people ?? []).filter((p) => p.name?.toLowerCase().includes(q)).slice(0, 6);
  }, [people, v]);

  const submit = (name: string, personId?: number) => {
    if (!name.trim()) return;
    onSubmit({ name: name.trim(), personId });
    setOpen(false);
  };

  return (
    <div className={clsx('relative', className)}>
      <input
        ref={ref}
        value={v}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => {
          setV(e.target.value);
          setOpen(true);
          setHi(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHi((h) => Math.min(h + 1, matches.length));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHi((h) => Math.max(h - 1, 0));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            const m = hi > 0 ? matches[hi - 1] : matches.find((p) => p.name?.toLowerCase() === v.trim().toLowerCase());
            if (m) submit(m.name!, m.id);
            else submit(v);
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
        aria-label={placeholder}
        className={clsx(
          'h-9 w-full rounded-lg border px-3 text-sm focus:outline-none focus:ring-2',
          dark
            ? 'border-white/20 bg-white/10 text-white placeholder:text-white/55 focus:border-[#8fb1fb] focus:ring-[#8fb1fb]/30'
            : 'border-line-strong bg-surface text-fg placeholder:text-fg-3 focus:border-accent focus:ring-accent/20',
        )}
      />
      {open && v.trim() && (
        <div
          className={clsx(
            'absolute left-0 right-0 top-10 z-30 overflow-hidden rounded-xl border p-1 shadow-pop',
            dark ? 'border-white/15 bg-[#1f1f1f] text-white' : 'border-line bg-surface',
          )}
        >
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => submit(v)}
            className={clsx('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm', hi === 0 && (dark ? 'bg-white/10' : 'bg-surface-2'))}
          >
            <Check className={clsx('size-4', dark ? 'text-[#8fb1fb]' : 'text-accent')} />
            {matches.some((m) => m.name?.toLowerCase() === v.trim().toLowerCase())
              ? `Use “${v.trim()}”`
              : `${kind === 'pet' ? 'New pet' : 'New person'} “${v.trim()}”`}
          </button>
          {matches.map((p, i) => (
            <button
              key={p.id}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => submit(p.name!, p.id)}
              className={clsx('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm', hi === i + 1 && (dark ? 'bg-white/10' : 'bg-surface-2'))}
            >
              <FaceAvatar faceId={p.cover_face_id} size={22} kind={kind} />
              <span className="flex-1">{p.name}</span>
              <span className={clsx('text-xs', dark ? 'text-white/55' : 'text-fg-3')}>{p.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
