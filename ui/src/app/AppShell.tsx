import { useQuery } from '@tanstack/react-query';
import { clsx } from 'clsx';
import {
  CheckCircle2,
  Compass,
  FolderOpen,
  History,
  House,
  Images,
  Lock,
  LockOpen,
  MessageCircleQuestion,
  Pause,
  Play,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router';
import { Badge, Button, IconButton, Kbd, Progress, Spinner, Tip } from '../components/ui';
import { get, post } from '../lib/api';
import { num } from '../lib/format';
import { useLive } from '../lib/live';
import type { Stats } from '../lib/types';
import { CommandPalette, usePalette } from './CommandPalette';
import { SelectionBar } from './SelectionBar';
import { PrivateUnlockDialog, usePrivateUi } from '../features/private/PrivateLock';
import { FolderBrowserDialog } from '../features/library/FolderBrowser';
import { CopyDialog, useOpNotifications } from '../features/ops/CopyDialog';
import { Viewer } from '../features/viewer/Viewer';

export function AppShell() {
  const openPalette = usePalette((s) => s.setOpen);
  useOpNotifications();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openPalette(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [openPalette]);

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="relative min-w-0 flex-1 overflow-hidden bg-canvas">
          <Outlet />
        </main>
      </div>
      <StatusBar />
      <CommandPalette />
      <PrivateUnlockDialog />
      <FolderBrowserDialog />
      <CopyDialog />
      <Viewer />
    </div>
  );
}

function TopBar() {
  const openPalette = usePalette((s) => s.setOpen);
  const priv = useLive((s) => s.privateState);
  const lockUi = usePrivateUi();
  const unlocked = !!priv?.unlocked;
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line bg-surface px-3">
      <div className="flex w-[204px] items-center gap-2 pl-1">
        <img src="./icon.png" alt="" className="size-7 rounded-lg" />
        <span className="text-[15px] font-semibold tracking-tight">RecPro</span>
      </div>
      <button
        type="button"
        onClick={() => openPalette(true)}
        className="flex h-9 min-w-0 max-w-xl flex-1 items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 text-left text-sm text-fg-3 transition-colors hover:border-line-strong"
      >
        <Search className="size-4 shrink-0" />
        <span className="truncate">Search people, things, places, text…</span>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <Kbd>Ctrl</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>
      <div className="ml-auto flex items-center gap-1.5">
        <Tip label="Nothing leaves this PC. RecPro analyzes photos and videos on this computer only and sends nothing to any server.">
          <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-ok-soft px-2.5 text-[13px] font-medium text-ok">
            <ShieldCheck className="size-4" />
            Local only
          </span>
        </Tip>
        <IconButton
          label={unlocked ? 'Private is unlocked. Click to lock now (Ctrl+L)' : 'Private is locked'}
          onClick={() => (unlocked ? void post('/api/private/lock') : lockUi.ask())}
          className={unlocked ? 'text-private hover:text-private' : ''}
        >
          {unlocked ? <LockOpen className="size-[18px]" /> : <Lock className="size-[18px]" />}
        </IconButton>
      </div>
    </header>
  );
}

const NAV = [
  { to: '/', label: 'Home', icon: House, end: true },
  { to: '/photos', label: 'Photos', icon: Images },
  { to: '/people', label: 'People', icon: Users },
  { to: '/explore', label: 'Explore', icon: Compass },
  { to: '/review', label: 'Review', icon: MessageCircleQuestion, count: 'review' as const },
  { to: '/private', label: 'Private', icon: Lock, private: true },
  { to: '/folders', label: 'Folders', icon: FolderOpen },
  { to: '/history', label: 'History and bin', icon: History },
];

function Sidebar() {
  const counts = useLive((s) => s.reviewCounts);
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: () => get<Stats>('/api/stats'), refetchInterval: 15000 });
  const review = counts.total ?? stats?.review ?? 0;
  return (
    <nav className="flex w-[216px] shrink-0 flex-col border-r border-line bg-surface px-2 py-3" aria-label="Main">
      <div className="flex flex-col gap-0.5">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              clsx(
                'flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium transition-colors',
                isActive ? 'bg-surface-2 text-fg' : 'text-fg-2 hover:bg-surface-2/70 hover:text-fg',
              )
            }
          >
            <n.icon className={clsx('size-[18px]', n.private && 'text-private')} />
            <span className="flex-1">{n.label}</span>
            {n.count === 'review' && review > 0 && <Badge tone="warn">{num(review)}</Badge>}
          </NavLink>
        ))}
      </div>
      <div className="mt-auto flex flex-col gap-0.5">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            clsx(
              'flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium transition-colors',
              isActive ? 'bg-surface-2 text-fg' : 'text-fg-2 hover:bg-surface-2/70 hover:text-fg',
            )
          }
        >
          <SettingsIcon className="size-[18px]" />
          Settings
        </NavLink>
      </div>
    </nav>
  );
}

function StatusBar() {
  const connected = useLive((s) => s.connected);
  const status = useLive((s) => s.status);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  let left: React.ReactNode;
  if (!connected) {
    left = (
      <span className="flex items-center gap-2 text-fg-2">
        <Spinner /> Connecting to the local engine…
      </span>
    );
  } else if (status && (status.running || status.scanning)) {
    const stage = Object.entries(status.stages).find(([, s]) => s.total > 0 && s.done < s.total);
    const s = stage?.[1];
    const pct = s && s.total ? (s.done / s.total) * 100 : 0;
    left = (
      <div className="flex min-w-0 items-center gap-3">
        {status.paused ? <Pause className="size-4 text-warn" /> : <Spinner className="text-accent" />}
        <span className="truncate text-fg-2">
          {status.paused ? 'Paused · ' : ''}
          {status.scanning && !s ? 'Looking for photos and videos…' : s ? `${s.label} ${num(s.done)} of ${num(s.total)}` : 'Working…'}
          {s?.rate ? ` · ${s.rate.toFixed(0)}/s` : ''}
        </span>
        {s && <Progress value={pct} className="w-32" />}
        <Button
          size="xs"
          variant="ghost"
          loading={busy}
          icon={status.paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
          onClick={async () => {
            setBusy(true);
            try {
              await post(status.paused ? '/api/index/resume' : '/api/index/pause');
            } finally {
              setBusy(false);
            }
          }}
        >
          {status.paused ? 'Resume' : 'Pause'}
        </Button>
      </div>
    );
  } else {
    left = (
      <button type="button" className="flex items-center gap-2 text-fg-2 hover:text-fg" onClick={() => nav('/folders')}>
        <CheckCircle2 className="size-4 text-ok" />
        {status && status.totalMedia > 0 ? `Library up to date · ${num(status.totalMedia)} items` : 'Ready'}
      </button>
    );
  }

  return (
    <footer className="flex h-10 shrink-0 items-center gap-4 border-t border-line bg-surface px-4 text-[13px]">
      <div className="min-w-0 flex-1">{left}</div>
      <SelectionBar />
    </footer>
  );
}
