import { useQuery } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { ChevronLeft, ChevronRight, Copy, ExternalLink, FolderOpen, Info, Lock, MapPin, Maximize2, Minimize2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { ApiError, get, mediaUrl, post } from '../../lib/api';
import { bridge } from '../../lib/bridge';
import { bytes, clock, dateTime, duration } from '../../lib/format';
import { useSelection } from '../../lib/selection';
import type { MediaDetail } from '../../lib/types';
import { useCopyFlow } from '../ops/CopyFlow';
import { useViewer } from './viewerStore';

const SRC_LABEL: Record<string, string> = {
  exif: 'from the camera',
  video: 'from the video',
  filename: 'from the file name',
  file: 'from the file date',
};

export function Viewer() {
  const { open, ids, index, go, close, startAt } = useViewer();
  const nav = useNavigate();
  const [info, setInfo] = useState(() => {
    try {
      return localStorage.getItem('recpro.viewer.info') !== '0';
    } catch {
      return true;
    }
  });
  const [actual, setActual] = useState(false);
  const id = ids[index];

  const detail = useQuery({
    queryKey: ['media', 'detail', id],
    queryFn: () => get<MediaDetail>(`/api/media/${id}`),
    enabled: open && id != null,
    retry: false,
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowRight') go(1);
      else if (e.key === 'ArrowLeft') go(-1);
      else if (e.key.toLowerCase() === 'i' && !e.ctrlKey) setInfo((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, go, close]);

  useEffect(() => {
    try {
      localStorage.setItem('recpro.viewer.info', info ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [info]);

  useEffect(() => setActual(false), [id]);

  // Prefetch neighbours for instant arrow navigation
  useEffect(() => {
    if (!open) return;
    [ids[index + 1], ids[index - 1]].forEach((n) => {
      if (n != null) {
        const img = new Image();
        img.src = mediaUrl(`media/preview/${n}`);
      }
    });
  }, [open, ids, index]);

  if (!open || id == null) return null;
  const d = detail.data;
  const locked = detail.error instanceof ApiError && detail.error.status === 423;

  return (
    <div className="fixed inset-0 z-40 flex bg-[#0b0b0b] text-white" role="dialog" aria-modal="true" aria-label="Viewer">
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="absolute inset-x-0 top-0 z-10 flex items-center gap-2 bg-gradient-to-b from-black/70 to-transparent px-3 py-2.5">
          <ViewerButton label="Close (Esc)" onClick={close}>
            <X className="size-5" />
          </ViewerButton>
          <div className="min-w-0 flex-1 px-2">
            <div className="truncate text-sm font-medium">{d ? dateTime(d.taken_at) : ''}</div>
            <div className="truncate text-xs text-white/60">{d?.name}</div>
          </div>
          <span className="text-xs text-white/60">
            {index + 1} / {ids.length}
          </span>
          {d?.kind === 'image' && (
            <ViewerButton label={actual ? 'Fit to screen' : 'Show larger'} onClick={() => setActual((v) => !v)}>
              {actual ? <Minimize2 className="size-5" /> : <Maximize2 className="size-5" />}
            </ViewerButton>
          )}
          {bridge && d && (
            <ViewerButton label="Show in folder" onClick={() => bridge!.showInExplorer(d.path)}>
              <FolderOpen className="size-5" />
            </ViewerButton>
          )}
          <ViewerButton label="Copy to…" onClick={() => useCopyFlow.getState().start([id], 'copy')}>
            <Copy className="size-5" />
          </ViewerButton>
          <ViewerButton label="Select" onClick={() => useSelection.getState().toggle(id, 'viewer')}>
            <span className="text-sm">Select</span>
          </ViewerButton>
          <ViewerButton label="Info (I)" onClick={() => setInfo((v) => !v)} active={info}>
            <Info className="size-5" />
          </ViewerButton>
        </div>

        <div className={clsx('flex min-h-0 flex-1 items-center justify-center', actual ? 'overflow-auto' : 'overflow-hidden')}>
          {locked ? (
            <div className="flex flex-col items-center gap-3 text-white/70">
              <Lock className="size-8" />
              This item is private. Unlock Private to see it.
            </div>
          ) : d?.kind === 'video' ? (
            <VideoView id={id} d={d} startMs={startAt[id]} />
          ) : (
            <img
              key={id}
              src={mediaUrl(`media/preview/${id}`)}
              alt={d?.name ?? ''}
              className={clsx('select-none', actual ? 'max-w-none' : 'max-h-full max-w-full object-contain')}
              draggable={false}
            />
          )}
        </div>

        {index > 0 && (
          <button type="button" aria-label="Previous (←)" onClick={() => go(-1)} className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-2.5 hover:bg-white/20">
            <ChevronLeft className="size-6" />
          </button>
        )}
        {index < ids.length - 1 && (
          <button type="button" aria-label="Next (→)" onClick={() => go(1)} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-white/10 p-2.5 hover:bg-white/20">
            <ChevronRight className="size-6" />
          </button>
        )}
      </div>

      {info && d && (
        <aside className="w-80 shrink-0 overflow-y-auto border-l border-white/10 bg-[#141414] p-5 text-sm">
          <h2 className="mb-4 text-[15px] font-semibold">Details</h2>
          <InfoRow label="Date" value={dateTime(d.taken_at)} hint={d.taken_src ? SRC_LABEL[d.taken_src] : undefined} />
          <InfoRow label="File" value={d.name} hint={`${bytes(d.size)}${d.width ? ` · ${d.width} × ${d.height}` : ''}${d.duration ? ` · ${duration(d.duration)}` : ''}`} />
          <InfoRow
            label="Folder"
            value={d.rel_dir ? `${d.folder_path}\\${d.rel_dir}` : d.folder_path}
            action={bridge ? <button type="button" className="text-xs text-[#8fb1fb] hover:underline" onClick={() => bridge!.showInExplorer(d.path)}>Show in folder</button> : undefined}
          />
          {d.camera && <InfoRow label="Camera" value={d.camera} />}
          {d.place ? (
            <InfoRow
              label="Place"
              value={[d.place.locality, d.place.city, d.place.admin1 !== d.place.city ? d.place.admin1 : null, d.place.country].filter(Boolean).join(', ')}
              hint={d.gps_lat != null ? `${d.gps_lat.toFixed(4)}, ${d.gps_lon?.toFixed(4)}` : undefined}
              icon={<MapPin className="size-3.5 shrink-0" />}
              action={
                <button
                  type="button"
                  className="text-xs text-[#8fb1fb] hover:underline"
                  onClick={() => {
                    close();
                    nav(`/places?city=${d.place!.city_id}`);
                  }}
                >
                  On the map
                </button>
              }
            />
          ) : (
            d.gps_lat != null && <InfoRow label="Place" value={`${d.gps_lat.toFixed(4)}, ${d.gps_lon?.toFixed(4)}`} icon={<MapPin className="size-3.5" />} />
          )}
          {d.faces.length > 0 && (
            <div className="mt-5">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/50">People</div>
              <div className="flex flex-wrap gap-2">
                {d.faces.map((f) => (
                  <span key={f.id} className="flex items-center gap-2 rounded-full bg-white/10 py-1 pl-1 pr-3 text-xs">
                    <img src={mediaUrl(`media/face/${f.id}?size=64`)} alt="" className="size-6 rounded-full object-cover" />
                    {f.person_name ?? 'Unnamed'}
                    {f.state === 'suggested' && <span className="text-[#e5a94a]">?</span>}
                  </span>
                ))}
              </div>
            </div>
          )}
          {d.labels.length > 0 && (
            <div className="mt-5">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/50">Found in this {d.kind === 'video' ? 'video' : 'photo'}</div>
              <div className="flex flex-wrap gap-1.5">
                {d.labels.map((l) => (
                  <span key={l.label_id} className={clsx('rounded-md px-2 py-0.5 text-xs', l.tier === 'sure' || l.state === 'confirmed' ? 'bg-white/12' : 'bg-[#3a2a10] text-[#e5a94a]')}>
                    {l.name}
                    {l.tier === 'check' && l.state === 'ai' ? ' ?' : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
          {d.text && (
            <div className="mt-5">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/50">Text in this photo</div>
              <p className="whitespace-pre-wrap text-xs text-white/70">{d.text.slice(0, 600)}</p>
            </div>
          )}
          {d.speech && d.speech.length > 0 && (
            <div className="mt-5">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/50">Said in this video</div>
              <ol className="space-y-1.5">
                {d.speech.slice(0, 300).map((sp) => (
                  <li key={sp.start_ms}>
                    <button
                      type="button"
                      onClick={() => window.dispatchEvent(new CustomEvent('recpro:seek', { detail: sp.start_ms }))}
                      className="flex w-full gap-2 rounded-md px-1.5 py-1 text-left text-xs text-white/75 hover:bg-white/10"
                    >
                      <span className="shrink-0 tabular-nums text-[#8fb1fb]">{clock(sp.start_ms)}</span>
                      <span>{sp.text}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

type PlayableState = { state: 'none' | 'making' | 'ready' | 'failed'; progress: number; error?: string };
type Lane = { key: string; label: string; avatar?: string; spans: { start_ms: number; end_ms: number }[]; tone: 'person' | 'private' | 'label' };

const TONE: Record<Lane['tone'], string> = { person: 'bg-[#8fb1fb]', private: 'bg-[#c39bf5]', label: 'bg-white/45' };

function VideoView({ id, d, startMs }: { id: number; d: MediaDetail; startMs?: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [src, setSrc] = useState<'original' | 'playable'>('original');
  const [making, setMaking] = useState<PlayableState | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    setSrc('original');
    setMaking(null);
    setFailed(null);
    setNow(0);
    // a copy made earlier plays right away (HEVC and other codecs this player may not open)
    if (d.vcodec && !/^(h264|avc)/i.test(d.vcodec)) {
      get<PlayableState>(`/api/media/${id}/playable`)
        .then((st) => st.state === 'ready' && setSrc('playable'))
        .catch(() => {});
    }
  }, [id, d.vcodec]);

  useEffect(() => {
    if (making?.state !== 'making') return;
    const t = setInterval(async () => {
      try {
        const st = await get<PlayableState>(`/api/media/${id}/playable`);
        if (st.state === 'ready') {
          setMaking(null);
          setSrc('playable');
        } else if (st.state === 'failed') {
          setMaking(null);
          setFailed(st.error ? `RecPro couldn’t make a playable copy (${st.error}).` : 'RecPro couldn’t make a playable copy.');
        } else setMaking(st);
      } catch {
        /* try again next tick */
      }
    }, 1000);
    return () => clearInterval(t);
  }, [making?.state, id]);

  const onError = async () => {
    if (src === 'playable') {
      setFailed('This video can’t play inside RecPro.');
      return;
    }
    try {
      const st = await post<PlayableState>(`/api/media/${id}/playable`);
      if (st.state === 'ready') setSrc('playable');
      else setMaking(st);
    } catch (e) {
      setFailed(e instanceof ApiError ? e.message : 'This video’s format can’t play inside RecPro.');
    }
  };

  const seek = (ms: number) => {
    const v = ref.current;
    if (!v) return;
    v.currentTime = ms / 1000;
    void v.play().catch(() => {});
  };

  // the details panel's transcript asks to jump to a moment
  useEffect(() => {
    const onSeek = (e: Event) => {
      const v = ref.current;
      const ms = (e as CustomEvent<number>).detail;
      if (v && typeof ms === 'number') {
        v.currentTime = ms / 1000;
        void v.play().catch(() => {});
      }
    };
    window.addEventListener('recpro:seek', onSeek);
    return () => window.removeEventListener('recpro:seek', onSeek);
  }, []);

  const lanes = useMemo(() => {
    const out: Lane[] = [];
    for (const f of d.faces) {
      if (f.spans?.length) {
        out.push({ key: `f${f.id}`, label: f.person_name ?? 'Unnamed person', avatar: mediaUrl(`media/face/${f.id}?size=64`), spans: f.spans, tone: 'person' });
      }
    }
    const grp = new Map(d.labels.map((l) => [l.label_id, l.grp]));
    const byLabel = new Map<number, Lane>();
    for (const sp of d.label_spans ?? []) {
      let lane = byLabel.get(sp.label_id);
      if (!lane) {
        lane = { key: `l${sp.label_id}`, label: sp.name, spans: [], tone: grp.get(sp.label_id) === 'sensitive' ? 'private' : 'label' };
        byLabel.set(sp.label_id, lane);
      }
      lane.spans.push(sp);
    }
    const labelLanes = [...byLabel.values()];
    return [...out, ...labelLanes.filter((l) => l.tone === 'private'), ...labelLanes.filter((l) => l.tone === 'label')];
  }, [d]);

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 px-16 pb-5 pt-16">
      <div className="flex min-h-0 w-full flex-1 items-center justify-center">
        {failed ? (
          <div className="flex max-w-sm flex-col items-center gap-3 text-center text-white/70">
            {failed}
            {bridge && (
              <button type="button" onClick={() => bridge!.openPath(d.path)} className="flex items-center gap-2 rounded-lg bg-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/20">
                <ExternalLink className="size-4" /> Open in your video player
              </button>
            )}
          </div>
        ) : making ? (
          <div className="flex w-72 flex-col items-center gap-3 text-center text-sm text-white/75">
            This video’s format doesn’t play here, so RecPro is making a playable copy.
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/15">
              <div className="h-full rounded-full bg-[#8fb1fb] transition-[width]" style={{ width: `${making.progress}%` }} />
            </div>
            <span className="text-xs text-white/50">{making.progress}%</span>
          </div>
        ) : (
          <video
            key={`${id}-${src}`}
            ref={ref}
            src={mediaUrl(src === 'playable' ? `media/playable/${id}` : `media/original/${id}`)}
            controls
            autoPlay
            className="max-h-full max-w-full"
            onError={() => void onError()}
            onLoadedMetadata={(e) => {
              if (startMs) e.currentTarget.currentTime = startMs / 1000;
            }}
            onTimeUpdate={(e) => setNow(e.currentTarget.currentTime * 1000)}
          />
        )}
      </div>
      {lanes.length > 0 && !failed && !making && <VideoLanes lanes={lanes} durMs={(d.duration ?? 0) * 1000} now={now} onSeek={seek} />}
    </div>
  );
}

/** One row per person and category: when they're in the video. Click a stretch to jump there. */
function VideoLanes({ lanes, durMs, now, onSeek }: { lanes: Lane[]; durMs: number; now: number; onSeek: (ms: number) => void }) {
  if (!durMs) return null;
  const pct = (ms: number) => `${Math.min(100, Math.max(0, (ms / durMs) * 100))}%`;
  return (
    <div className="w-full max-w-4xl space-y-1.5" aria-label="When people and things are in this video">
      {lanes.slice(0, 12).map((l) => (
        <div key={l.key} className="flex items-center gap-3">
          <div className="flex w-44 shrink-0 items-center gap-2 text-xs text-white/80">
            {l.avatar ? <img src={l.avatar} alt="" className="size-5 shrink-0 rounded-full object-cover" /> : <span className={clsx('size-2 shrink-0 rounded-full', TONE[l.tone])} />}
            <span className="truncate">{l.label}</span>
          </div>
          <div className="relative h-3 flex-1 rounded-full bg-white/10">
            {l.spans.map((sp) => (
              <button
                key={`${sp.start_ms}-${sp.end_ms}`}
                type="button"
                aria-label={`${l.label}, ${clock(sp.start_ms)} to ${clock(sp.end_ms)}`}
                title={`${clock(sp.start_ms)}–${clock(sp.end_ms)}`}
                onClick={() => onSeek(sp.start_ms)}
                className={clsx('absolute inset-y-0 min-w-1 rounded-full hover:brightness-125', TONE[l.tone])}
                style={{ left: pct(sp.start_ms), width: `${((sp.end_ms - sp.start_ms) / durMs) * 100}%` }}
              />
            ))}
            <div className="pointer-events-none absolute -inset-y-1 w-0.5 rounded bg-white" style={{ left: pct(now) }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ViewerButton({ label, onClick, children, active }: { label: string; onClick: () => void; children: React.ReactNode; active?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={clsx('flex h-9 min-w-9 items-center justify-center rounded-lg px-2 text-white/85 hover:bg-white/10 hover:text-white', active && 'bg-white/15')}
    >
      {children}
    </button>
  );
}

function InfoRow({ label, value, hint, action, icon }: { label: string; value: string; hint?: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="mb-3.5">
      <div className="text-xs text-white/50">{label}</div>
      <div className="mt-0.5 flex items-center gap-1.5 break-all text-[13px] text-white/90">
        {icon}
        {value}
      </div>
      {hint && <div className="text-xs text-white/45">{hint}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
