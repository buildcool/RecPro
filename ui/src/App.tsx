import { useQuery } from '@tanstack/react-query';
import { Compass } from 'lucide-react';
import { lazy, Suspense, useEffect } from 'react';
import { createHashRouter, Navigate, Outlet, RouterProvider, useLocation } from 'react-router';
import { AppShell } from './app/AppShell';
import { Spinner } from './components/ui';
import { usePrivateActivity, usePrivateHotkeys } from './features/private/PrivateLock';
import { get } from './lib/api';
import { setTheme, type ThemePref } from './lib/theme';
import type { Settings } from './lib/types';
import { Placeholder } from './pages/Placeholder';

const lazyPage = (name: string, loader: () => Promise<Record<string, React.ComponentType>>) =>
  lazy(async () => ({ default: (await loader())[name] }));

const Home = lazyPage('HomePage', () => import('./pages/Home'));
const Photos = lazyPage('PhotosPage', () => import('./pages/Photos'));
const HistoryPage = lazyPage('HistoryPage', () => import('./pages/History'));
const PeoplePage = lazyPage('PeoplePage', () => import('./pages/People'));
const PersonPage = lazyPage('PersonPage', () => import('./pages/Person'));
const ReviewPage = lazyPage('ReviewPage', () => import('./pages/Review'));
const FindPage = lazyPage('FindPage', () => import('./pages/Find'));
const PrivatePage = lazyPage('PrivatePage', () => import('./pages/Private'));
const Folders = lazyPage('FoldersPage', () => import('./pages/Folders'));
const Settings = lazyPage('SettingsPage', () => import('./pages/Settings'));
const Onboarding = lazyPage('OnboardingPage', () => import('./pages/Onboarding'));

function Gate() {
  const loc = useLocation();
  const { data: settings, isLoading } = useQuery({ queryKey: ['settings'], queryFn: () => get<Settings>('/api/settings'), retry: 30, retryDelay: 1000 });
  usePrivateHotkeys();
  usePrivateActivity();
  useEffect(() => {
    if (settings?.theme) setTheme(settings.theme as ThemePref);
  }, [settings?.theme]);
  if (isLoading || !settings) {
    return (
      <div className="flex h-full items-center justify-center gap-3 text-fg-2">
        <Spinner /> Starting RecPro…
      </div>
    );
  }
  if (!settings.onboarded && loc.pathname !== '/welcome') return <Navigate to="/welcome" replace />;
  return <Outlet />;
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Spinner />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

const router = createHashRouter([
  {
    element: <Gate />,
    children: [
      { path: '/welcome', element: <Page><Onboarding /></Page> },
      {
        element: <AppShell />,
        children: [
          { path: '/', element: <Page><Home /></Page> },
          { path: '/photos', element: <Page><Photos /></Page> },
          { path: '/people', element: <Page><PeoplePage /></Page> },
          { path: '/people/:id', element: <Page><PersonPage /></Page> },
          { path: '/find', element: <Page><FindPage /></Page> },
          { path: '/explore', element: <Placeholder title="Explore" icon={<Compass className="size-6" />} /> },
          { path: '/review', element: <Page><ReviewPage /></Page> },
          { path: '/private', element: <Page><PrivatePage /></Page> },
          { path: '/folders', element: <Page><Folders /></Page> },
          { path: '/history', element: <Page><HistoryPage /></Page> },
          { path: '/settings', element: <Page><Settings /></Page> },
          { path: '*', element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
