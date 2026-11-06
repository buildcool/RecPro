import { clsx } from 'clsx';
import { Check } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { useNamedPeople } from '../../lib/people';
import { FaceAvatar } from './FaceAvatar';

/** Text input that suggests existing names; picking one means "same person". */
export function NameInput({
  onSubmit,
  placeholder = 'Add a name',
  autoFocus,
  initial = '',
  className,
}: {
  onSubmit: (value: { name: string; personId?: number }) => void;
  placeholder?: string;
  autoFocus?: boolean;
  initial?: string;
  className?: string;
}) {
  const { data: people } = useNamedPeople();
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
        className="h-9 w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
      />
      {open && v.trim() && (
        <div className="absolute left-0 right-0 top-10 z-30 overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-pop">
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => submit(v)}
            className={clsx('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm', hi === 0 && 'bg-surface-2')}
          >
            <Check className="size-4 text-accent" />
            {matches.some((m) => m.name?.toLowerCase() === v.trim().toLowerCase()) ? `Use “${v.trim()}”` : `New person “${v.trim()}”`}
          </button>
          {matches.map((p, i) => (
            <button
              key={p.id}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => submit(p.name!, p.id)}
              className={clsx('flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm', hi === i + 1 && 'bg-surface-2')}
            >
              <FaceAvatar faceId={p.cover_face_id} size={22} />
              <span className="flex-1">{p.name}</span>
              <span className="text-xs text-fg-3">{p.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
