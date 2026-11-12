import { clsx } from 'clsx';
import { PawPrint, UserRound } from 'lucide-react';
import { mediaUrl } from '../../lib/api';
import type { Kind } from '../../lib/people';

/** A face crop in a circle, or with kind="pet" the crop of an animal. */
export function FaceAvatar({
  faceId,
  size = 56,
  className,
  ring,
  kind = 'human',
}: {
  faceId: number | null | undefined;
  size?: number;
  className?: string;
  ring?: boolean;
  kind?: Kind;
}) {
  const px = size <= 64 ? 96 : size <= 128 ? 160 : 256;
  if (!faceId) {
    const Icon = kind === 'pet' ? PawPrint : UserRound;
    return (
      <span className={clsx('flex shrink-0 items-center justify-center rounded-full bg-surface-2 text-fg-3', className)} style={{ width: size, height: size }}>
        <Icon style={{ width: size * 0.45, height: size * 0.45 }} />
      </span>
    );
  }
  return (
    <img
      src={mediaUrl(`media/${kind === 'pet' ? 'animal' : 'face'}/${faceId}?size=${px}`)}
      alt=""
      loading="lazy"
      draggable={false}
      className={clsx('shrink-0 rounded-full bg-thumb object-cover', ring && 'ring-2 ring-surface', className)}
      style={{ width: size, height: size }}
    />
  );
}

export function FaceStack({ faceIds, size = 28, kind = 'human' }: { faceIds: number[]; size?: number; kind?: Kind }) {
  return (
    <span className="flex -space-x-2">
      {faceIds.slice(0, 4).map((f) => (
        <FaceAvatar key={f} faceId={f} size={size} ring kind={kind} />
      ))}
    </span>
  );
}
