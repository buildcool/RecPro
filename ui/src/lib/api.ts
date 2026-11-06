import { bridge } from './bridge';

let base = '';
let token = '';

export function initEngine() {
  const e = bridge?.engine;
  if (e) {
    base = `http://127.0.0.1:${e.port}`;
    token = e.token;
  } else {
    base = (import.meta.env.VITE_ENGINE_URL as string | undefined) ?? 'http://127.0.0.1:47321';
    token = (import.meta.env.VITE_ENGINE_TOKEN as string | undefined) ?? 'devtoken';
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Opts = { method?: string; body?: unknown; signal?: AbortSignal };

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-RecPro-Token': token };
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, { method: opts.method ?? 'GET', headers, body, signal: opts.signal });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, "Can't reach the RecPro engine. It may still be starting.");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === 'string') msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d: { msg?: string }) => d.msg).join('; ');
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Multipart upload to the local engine (e.g. reference photos in browser mode). */
export async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${base}${path}`, { method: 'POST', headers: { 'X-RecPro-Token': token }, body: form });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = (await res.json()) as { detail?: string };
      if (typeof j.detail === 'string') msg = j.detail;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body });
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' });

/** URL for an engine-served image/video. Desktop: through the app's private protocol. */
export function mediaUrl(path: string): string {
  const p = path.replace(/^\/+/, '');
  if (bridge?.engine) return `recpro-media://e/${p}`;
  return `${base}/${p}${p.includes('?') ? '&' : '?'}t=${token}`;
}

export function wsUrl(): string {
  return `${base.replace(/^http/, 'ws')}/ws?t=${token}`;
}

export function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}
