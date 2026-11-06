import '@fontsource-variable/inter';
import './styles.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Toaster } from 'sonner';
import { App } from './App';
import { TooltipProvider } from './components/ui';
import { initEngine } from './lib/api';
import { bridge } from './lib/bridge';
import { startLive } from './lib/live';
import { initTheme } from './lib/theme';

initTheme();
initEngine();

const qc = new QueryClient({
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
