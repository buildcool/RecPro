import { useQuery } from '@tanstack/react-query';
import { Command } from 'cmdk';
import { ArrowRight, Bookmark, Compass, FolderOpen, FolderPlus, History, House, Images, Lock, Luggage, MapPin, MessageCircleQuestion, PawPrint, Search, Settings, Sparkles, Tag, UserRound, Users, Wand2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { create } from 'zustand';
import * as DialogP from '@radix-ui/react-dialog';
import { get, mediaUrl } from '../lib/api';
import { addFoldersFlow } from '../features/library/addFolders';
import { savedHref, useSavedSearches } from '../features/search/saved';

export const usePalette = create<{ open: boolean; setOpen: (v: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

type PersonLite = { id: number; name: string | null; count: number; cover_face_id: number | null };
type LabelLite = { id: number; key: string; name: string; grp: string; count: number };

export function CommandPalette() {
  const { open, setOpen } = usePalette();
  const [q, setQ] = useState('');
  const nav = useNavigate();
  const people = useQuery({
    queryKey: ['people', 'palette'],
    queryFn: () => get<PersonLite[]>('/api/people?named=1'),
    enabled: open,
    retry: false,
  });
  const pets = useQuery({
    queryKey: ['people', 'pets', 'palette'],
    queryFn: () => get<PersonLite[]>('/api/people?kind=pet&named=1'),
    enabled: open,
    retry: false,
  });
  const labels = useQuery({
    queryKey: ['labels', 'palette'],
    queryFn: () => get<LabelLite[]>('/api/labels?used=1'),
    enabled: open,
    retry: false,
  });
  const saved = useSavedSearches();

  const go = (to: string) => {
    setOpen(false);
    setQ('');
    nav(to);
  };

  const item = 'flex h-10 cursor-pointer items-center gap-3 rounded-lg px-3 text-sm text-fg aria-selected:bg-surface-2';

  return (
    <DialogP.Root open={open} onOpenChange={setOpen}>
      <DialogP.Portal>
        <DialogP.Overlay className="fixed inset-0 z-50 bg-overlay" />
        <DialogP.Content className="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-2rem)] max-w-2xl -translate-x-1/2 overflow-hidden rounded-2xl border border-line bg-surface shadow-pop">
          <DialogP.Title className="sr-only">Search and commands</DialogP.Title>
          <DialogP.Description className="sr-only">Search your library or jump to a page</DialogP.Description>
          <Command label="Search and commands" loop>
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search className="size-5 text-fg-3" />
              <Command.Input
                value={q}
                onValueChange={setQ}
                autoFocus
                placeholder="Search people, things, places, text… or type a command"
                className="h-14 flex-1 bg-transparent text-[15px] text-fg outline-none placeholder:text-fg-3"
              />
            </div>
            <Command.List className="max-h-[60vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-fg-2">No matches. Press Enter to search everything.</Command.Empty>
              {q.trim() && (
                <Command.Group heading="Search" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  <Command.Item value={`search ${q}`} onSelect={() => go(`/search?q=${encodeURIComponent(q.trim())}`)} className={item}>
                    <Search className="size-4 text-accent" />
                    <span>
                      Search for <strong className="font-semibold">“{q.trim()}”</strong>
                    </span>
                    <ArrowRight className="ml-auto size-4 text-fg-3" />
                  </Command.Item>
                </Command.Group>
              )}
              {(people.data?.length ?? 0) > 0 && (
                <Command.Group heading="People" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  {people.data!.slice(0, 30).map((p) => (
                    <Command.Item key={p.id} value={`person ${p.name}`} onSelect={() => go(`/people/${p.id}`)} className={item}>
                      {p.cover_face_id ? (
                        <img src={mediaUrl(`media/face/${p.cover_face_id}`)} alt="" className="size-6 rounded-full object-cover" />
                      ) : (
                        <UserRound className="size-4 text-fg-3" />
                      )}
                      <span className="flex-1">{p.name}</span>
                      <span className="text-xs text-fg-3">{p.count} photos</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {(pets.data?.length ?? 0) > 0 && (
                <Command.Group heading="Pets" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  {pets.data!.slice(0, 30).map((p) => (
                    <Command.Item key={p.id} value={`pet ${p.name}`} onSelect={() => go(`/people/${p.id}`)} className={item}>
                      {p.cover_face_id ? (
                        <img src={mediaUrl(`media/animal/${p.cover_face_id}`)} alt="" className="size-6 rounded-full object-cover" />
                      ) : (
                        <PawPrint className="size-4 text-fg-3" />
                      )}
                      <span className="flex-1">{p.name}</span>
                      <span className="text-xs text-fg-3">{p.count} photos</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {(labels.data?.length ?? 0) > 0 && q.trim().length > 0 && (
                <Command.Group heading="Categories" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  {labels.data!.slice(0, 200).map((l) => (
                    <Command.Item key={l.id} value={`category ${l.name} ${l.grp}`} onSelect={() => go(`/explore/${l.id}`)} className={item}>
                      <Tag className="size-4 text-fg-3" />
                      <span className="flex-1">{l.name}</span>
                      <span className="text-xs text-fg-3">{l.count}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {(saved.data?.length ?? 0) > 0 && (
                <Command.Group heading="Saved searches" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                  {saved.data!.map((s) => (
                    <Command.Item key={s.id} value={`saved ${s.name} ${s.q}`} onSelect={() => go(savedHref(s))} className={item}>
                      <Bookmark className="size-4 text-fg-3" />
                      <span className="flex-1">{s.name}</span>
                      {s.name !== s.q && <span className="truncate text-xs text-fg-3">{s.q}</span>}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              <Command.Group heading="Actions" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                <Command.Item value="find and move person copy" onSelect={() => go('/find')} className={item}>
                  <Wand2 className="size-4 text-accent" /> Find and move someone’s photos
                </Command.Item>
                <Command.Item
                  value="add folder library"
                  onSelect={() => {
                    setOpen(false);
                    void addFoldersFlow();
                  }}
                  className={item}
                >
                  <FolderPlus className="size-4 text-fg-2" /> Add folders
                </Command.Item>
                <Command.Item value="review questions check" onSelect={() => go('/review')} className={item}>
                  <MessageCircleQuestion className="size-4 text-fg-2" /> Answer review questions
                </Command.Item>
              </Command.Group>
              <Command.Group heading="Go to" className="px-1 pb-1 text-xs text-fg-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                {[
                  { to: '/', label: 'Home', icon: House },
                  { to: '/photos', label: 'Photos', icon: Images },
                  { to: '/people', label: 'People', icon: Users },
                  { to: '/explore', label: 'Explore', icon: Compass },
                  { to: '/places', label: 'Places', icon: MapPin, keywords: ['map', 'location', 'where', 'travel', 'city', 'country'] },
                  { to: '/memories', label: 'Trips and events', icon: Luggage, keywords: ['trip', 'vacation', 'holiday', 'event', 'birthday', 'wedding', 'festival', 'memories'] },
                  { to: '/private', label: 'Private', icon: Lock },
                  { to: '/folders', label: 'Folders', icon: FolderOpen },
                  { to: '/cleanup', label: 'Clean up', icon: Sparkles, keywords: ['duplicates', 'copies', 'similar', 'blurry', 'dark', 'whatsapp', 'forwards', 'free space'] },
                  { to: '/history', label: 'History and bin', icon: History },
                  { to: '/settings', label: 'Settings', icon: Settings },
                ].map((p: { to: string; label: string; icon: typeof House; keywords?: string[] }) => (
                  <Command.Item key={p.to} value={`go ${p.label}`} keywords={p.keywords} onSelect={() => go(p.to)} className={item}>
                    <p.icon className="size-4 text-fg-2" /> {p.label}
                  </Command.Item>
                ))}
              </Command.Group>
            </Command.List>
          </Command>
        </DialogP.Content>
      </DialogP.Portal>
    </DialogP.Root>
  );
}
