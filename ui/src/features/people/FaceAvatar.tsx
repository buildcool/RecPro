import { clsx } from 'clsx';
import { UserRound } from 'lucide-react';
import { mediaUrl } from '../../lib/api';

export function FaceAvatar({ faceId, size = 56, className, ring }: { faceId: number | null | undefined; size?: number; className?: string; ring?: boolean }) {
  const px = size <= 64 ? 96 : size <= 128 ? 160 : 256;
  if (!faceId)
    return (
      <span className={clsx('flex shrink-0 items-center justify-center rounded-full bg-surface-2 text-fg-3', className)} style={{ width: size, height: size }}>
        <UserRound style={{ width: size * 0.45, height: size * 0.45 }} />
      </span>
    );
  return (
    <img
      src={mediaUrl(`media/face/${faceId}?size=${px}`)}
      alt=""
      loading="lazy"
      draggable={false}
      className={clsx('shrink-0 rounded-full bg-thumb object-cover', ring && 'ring-2 ring-surface', className)}
      style={{ width: size, height: size }}
    />
  );
}

export function FaceStack({ faceIds, size = 28 }: { faceIds: number[]; size?: number }) {
  return (
    <span className="flex -space-x-2">
      {faceIds.slice(0, 4).map((f) => (
        <FaceAvatar key={f} faceId={f} size={size} ring />
      ))}
    </span>
  );
}
