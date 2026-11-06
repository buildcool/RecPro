export type ThemePref = 'system' | 'light' | 'dark';

let current: ThemePref = 'system';
const mq = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null;

function apply() {
  const dark = current === 'dark' || (current === 'system' && !!mq?.matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

export function setTheme(pref: ThemePref) {
  current = pref;
  try {
    localStorage.setItem('recpro.theme', pref);
  } catch {
    /* storage unavailable */
  }
  apply();
}

export function initTheme() {
  try {
    const saved = localStorage.getItem('recpro.theme') as ThemePref | null;
    if (saved) current = saved;
  } catch {
    /* storage unavailable */
  }
  mq?.addEventListener('change', apply);
  apply();
}
