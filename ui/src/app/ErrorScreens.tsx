import { AlertTriangle, ClipboardCopy, House, RotateCw } from 'lucide-react';
import { useEffect } from 'react';
import { isRouteErrorResponse, useLocation, useNavigate, useRouteError } from 'react-router';
import { toast } from 'sonner';
import { Button } from '../components/ui';
import { post } from '../lib/api';
import { useHealth } from '../lib/queries';

function describe(err: unknown): { message: string; stack: string } {
  if (isRouteErrorResponse(err)) return { message: `${err.status} ${err.statusText}`, stack: typeof err.data === 'string' ? err.data : '' };
  if (err instanceof Error) return { message: err.message, stack: err.stack ?? '' };
  return { message: String(err), stack: '' };
}

/** After an update the window may still ask for the old version's code files, which are gone. */
const staleCode = (m: string) => /dynamically imported module|Importing a module script failed|Loading chunk/i.test(m);

/** Kept in the engine's log on this PC (logs/engine.log), next to its own errors. */
function useLogged(err: unknown, where: string) {
  useEffect(() => {
    const d = describe(err);
    void post('/api/diagnostics/ui-error', { where, message: d.message.slice(0, 500), stack: d.stack.slice(0, 4000) }).catch(() => undefined);
  }, [err, where]);
}

function ErrorBody({ full }: { full: boolean }) {
  const err = useRouteError();
  const nav = useNavigate();
  const loc = useLocation();
  const { data: health } = useHealth();
  const d = describe(err);
  useLogged(err, `${loc.pathname}${loc.search}`);
  const stale = staleCode(d.message);
  const details = `RecPro ${health?.version ?? ''} · ${loc.pathname}${loc.search}\n${d.message}\n${d.stack}`.trim();
  return (
    <div className={full ? 'flex h-full items-center justify-center bg-canvas p-8' : 'flex h-full items-center justify-center p-8'} role="alert">
      <div className="w-full max-w-lg text-center">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-warn-soft text-warn">
          <AlertTriangle className="size-6" />
        </div>
        <h1 className="text-lg font-semibold">{stale ? 'RecPro was updated' : full ? 'RecPro ran into a problem' : 'This screen ran into a problem'}</h1>
        <p className="mt-1.5 text-sm text-fg-2">
          {stale
            ? 'Reload to finish the update. Nothing is lost.'
            : `${full ? '' : 'The rest of RecPro still works. '}Nothing was changed: your photos, people and answers are safe.`}
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Button variant="primary" icon={<RotateCw className="size-4" />} onClick={() => window.location.reload()}>
            {stale ? 'Reload' : 'Try again'}
          </Button>
          {!stale && (
            <Button icon={<House className="size-4" />} onClick={() => (full ? window.location.assign('#/') : nav('/'))}>
              Go to Home
            </Button>
          )}
        </div>
        {!stale && (
          <details className="mt-6 text-left">
            <summary className="cursor-pointer text-xs text-fg-3">Details for a bug report</summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3 text-[11px] text-fg-2">{details}</pre>
            <Button
              size="xs"
              variant="ghost"
              className="mt-1"
              icon={<ClipboardCopy className="size-3.5" />}
              onClick={() =>
                void navigator.clipboard.writeText(details).then(
                  () => toast.success('Copied'),
                  () => toast.error('Couldn’t copy'),
                )
              }
            >
              Copy details
            </Button>
          </details>
        )}
      </div>
    </div>
  );
}

/** A screen that failed, shown in its place: the sidebar and everything else keep working. */
export function PageError() {
  return <ErrorBody full={false} />;
}

/** The window itself failed (the shell or start-up). */
export function AppError() {
  return <ErrorBody full />;
}
