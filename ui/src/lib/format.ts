const nf = new Intl.NumberFormat();

export const num = (n: number | null | undefined) => (n == null ? '–' : nf.format(Math.round(n)));

export function bytes(n: number | null | undefined): string {
  if (n == null) return '–';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function duration(sec: number | null | undefined): string {
  if (sec == null) return '';
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}

export function eta(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return '';
  if (sec < 60) return 'under a minute';
  const m = Math.round(sec / 60);
  if (m < 60) return `about ${m} min`;
  const h = Math.floor(m / 60);
  return `about ${h} h ${m % 60} min`;
}

const dfLong = new Intl.DateTimeFormat(undefined, { dateStyle: 'long' });
const dfMonth = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
const dfFull = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export const dateLong = (ts: number | null | undefined) => (ts ? dfLong.format(new Date(ts * 1000)) : 'Unknown date');
export const monthYear = (ts: number | null | undefined) => (ts ? dfMonth.format(new Date(ts * 1000)) : 'Unknown date');
export const dateTime = (ts: number | null | undefined) => (ts ? dfFull.format(new Date(ts * 1000)) : '–');

export function timeAgo(ts: number | null | undefined): string {
  if (!ts) return '';
  const d = Date.now() / 1000 - ts;
  if (d < 60) return 'just now';
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  if (d < 86400 * 7) return `${Math.floor(d / 86400)} days ago`;
  return dateLong(ts);
}

export const plural = (n: number, one: string, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;
