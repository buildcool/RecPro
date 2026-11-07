import '@fontsource-variable/inter';
import './styles.css';
import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { toast, Toaster } from 'sonner';
import { App } from './App';
import { TooltipProvider } from './components/ui';
import { ApiError, initEngine } from './lib/api';
import { bridge } from './lib/bridge';
import { startLive, useLive } from './lib/live';
import { initTheme } from './lib/theme';

initTheme();
initEngine();

const qc = new QueryClient({
  // anything that fails to load says so once, instead of leaving an empty screen; not while the
  // engine is restarting (the status bar says so), nor for the answers pages handle themselves
  // (not found, private and locked, nothing to show yet)
  queryCache: new QueryCache({
    onError: (err) => {
      if (err instanceof ApiError && [401, 404, 409, 423].includes(err.status)) return;
      if (!useLive.getState().connected) return;
      toast.error('Something didn’t load', { id: `load:${err.message}`, description: err.message });
    },
  }),
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
});
startLive(qc);
bridge?.onEngineRestart(() => window.location.reload());

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <App />
        <Toaster position="bottom-right" offset={56} theme="system" richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
