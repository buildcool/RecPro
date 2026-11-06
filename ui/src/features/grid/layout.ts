import justifiedLayout from 'justified-layout';
import type { MediaItem } from '../../lib/types';

export type Box = { left: number; top: number; width: number; height: number };

export const SPACING = 4;

export function aspect(item: Pick<MediaItem, 'w' | 'h'>): number {
  if (!item.w || !item.h) return 1;
  // Clamp extreme panoramas/strips so rows stay usable
  return Math.min(3, Math.max(0.4, item.w / item.h));
}

export function layoutItems(items: MediaItem[], width: number, rowHeight: number): { boxes: Box[]; height: number } {
  if (items.length === 0 || width <= 0) return { boxes: [], height: 0 };
  const res = justifiedLayout(
    items.map(aspect),
    {
      containerWidth: width,
      containerPadding: 0,
      boxSpacing: SPACING,
      targetRowHeight: rowHeight,
      targetRowHeightTolerance: 0.25,
    },
  );
  return { boxes: res.boxes, height: Math.ceil(res.containerHeight) };
}

export function estimateHeight(count: number, width: number, rowHeight: number): number {
  if (width <= 0) return count * 50;
  const perRow = Math.max(1, Math.floor(width / (rowHeight * 1.3 + SPACING)));
  return Math.ceil(count / perRow) * (rowHeight + SPACING);
}

export type ZoomLevel = 'small' | 'medium' | 'large';
export const ROW_HEIGHT: Record<ZoomLevel, number> = { small: 130, medium: 190, large: 270 };
