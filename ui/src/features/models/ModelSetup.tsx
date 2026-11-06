import { useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Cpu, Download, Loader2, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge, Button, Card, Progress } from '../../components/ui';
import { ApiError, post } from '../../lib/api';
import { bytes } from '../../lib/format';
import { type ModelInfo, useModels } from '../../lib/people';

/** Shown where a feature needs a model that isn't installed yet. */
export function ModelSetupCard({ need }: { need: string }) {
  const { data } = useModels();
  const qc = useQueryClient();
  const m = data?.models.find((x) => x.id === need);
  if (!data || !m || m.installed) return null;
  const busy = m.queued || m.progress?.state === 'downloading';
  const profile = data.profile || 'best';
  const set = data.models.filter((x) => x.profiles.includes(profile) && !x.installed);
  const total = set.reduce((a, x) => a + x.size, 0);
  return (
    <Card className="flex flex-wrap items-center gap-4 p-5">
      <div className="flex size-11 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
        <Cpu className="size-5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold">Set up recognition on this PC</div>
        <p className="text-[13px] text-fg-2">
          RecPro downloads its AI models once ({bytes(total)}). After that, everything runs offline on {data.device.name}. Nothing you have is uploaded.
        </p>
        {busy && <ModelProgress m={m} />}
      </div>
      {!busy && (
        <Button
          variant="primary"
          icon={<Download className="size-4" />}
          onClick={async () => {
            try {
              await post('/api/models/download', { profile });
              qc.invalidateQueries({ queryKey: ['models'] });
            } catch (e) {
              toast.error(e instanceof ApiError ? e.message : String(e));
            }
          }}
        >
          Download models
        </Button>
      )}
    </Card>
  );
}

function ModelProgress({ m }: { m: ModelInfo }) {
  const p = m.progress;
  const pct = p?.bytes_total ? ((p.bytes_done ?? 0) / p.bytes_total) * 100 : 0;
  return (
    <div className="mt-2 max-w-md">
      <Progress value={pct} />
      <div className="mt-1 text-xs text-fg-3">
        {m.queued && !p ? 'Waiting…' : `${bytes(p?.bytes_done ?? 0)} of ${bytes(p?.bytes_total ?? m.size)}`}
      </div>
    </div>
  );
}

/** Full list for Settings. */
export function ModelsList() {
  const { data } = useModels();
  const qc = useQueryClient();
  if (!data) return null;
  const profile = data.profile || 'best';
  const refresh = () => qc.invalidateQueries({ queryKey: ['models'] });
  return (
    <div className="divide-y divide-line">
      {data.models
        .filter((m) => m.profiles.includes(profile) || m.installed)
        .map((m) => {
          const st = m.progress?.state;
          const busy = m.queued || st === 'downloading';
          return (
            <div key={m.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium">
                  {m.name}
                  {m.installed && (
                    <Badge tone="ok">
                      <CheckCircle2 className="size-3" /> Ready
                    </Badge>
                  )}
                  {st === 'failed' && <Badge tone="bad">Failed</Badge>}
                </div>
                <div className="text-xs text-fg-3">
                  {m.purpose} · {bytes(m.size)} · {m.license}
                </div>
                {st === 'failed' && <div className="text-xs text-bad">{m.progress?.error}</div>}
                {busy && <ModelProgress m={m} />}
              </div>
              {!m.installed && !busy && (
                <Button
                  size="sm"
                  icon={<Download className="size-3.5" />}
                  onClick={async () => {
                    try {
                      await post('/api/models/download', { ids: [m.id] });
                      refresh();
                    } catch (e) {
                      toast.error((e as Error).message);
                    }
                  }}
                >
                  Download
                </Button>
              )}
              {busy && (
                <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={() => post(`/api/models/${m.id}/cancel`).then(refresh)}>
                  Cancel
                </Button>
              )}
              {busy && st === 'downloading' && <Loader2 className="size-4 animate-spin text-fg-3" />}
            </div>
          );
        })}
      <p className="pt-3 text-xs text-fg-3">Running on {data.device.name} ({data.device.provider}).</p>
    </div>
  );
}
