import type { ReactNode } from 'react';
import { EmptyState, PageHeader } from '../components/ui';

export function Placeholder({ title, icon, body }: { title: string; icon?: ReactNode; body?: string }) {
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title={title} />
      <EmptyState icon={icon} title={`${title} is on its way`} body={body ?? 'This part of RecPro is being built.'} />
    </div>
  );
}
