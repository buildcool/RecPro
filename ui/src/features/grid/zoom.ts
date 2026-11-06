import { create } from 'zustand';
import type { ZoomLevel } from './layout';

function initial(): ZoomLevel {
  try {
    const v = localStorage.getItem('recpro.zoom');
    if (v === 'small' || v === 'medium' || v === 'large') return v;
  } catch {
    /* ignore */
  }
  return 'medium';
}

export const useZoom = create<{ zoom: ZoomLevel; setZoom: (z: ZoomLevel) => void }>((set) => ({
  zoom: initial(),
  setZoom: (zoom) => {
    try {
      localStorage.setItem('recpro.zoom', zoom);
    } catch {
      /* ignore */
    }
    set({ zoom });
  },
}));
