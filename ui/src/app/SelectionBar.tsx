import { Copy, FolderInput, X } from 'lucide-react';
import { Button } from '../components/ui';
import { num } from '../lib/format';
import { useSelection } from '../lib/selection';
import { useCopyFlow } from '../features/ops/CopyFlow';

export function SelectionBar() {
  const ids = useSelection((s) => s.ids);
  const clear = useSelection((s) => s.clear);
  const startCopy = useCopyFlow((s) => s.start);
  if (ids.size === 0) return null;
  const list = [...ids];
  return (
    <div className="flex items-center gap-2">
      <span className="font-medium text-fg">{num(ids.size)} selected</span>
      <Button size="xs" variant="primary" icon={<Copy className="size-3.5" />} onClick={() => startCopy(list, 'copy')}>
        Copy to…
      </Button>
      <Button size="xs" variant="secondary" icon={<FolderInput className="size-3.5" />} onClick={() => startCopy(list, 'move')}>
        Move to…
      </Button>
      <Button size="xs" variant="ghost" icon={<X className="size-3.5" />} onClick={clear}>
        Clear
      </Button>
    </div>
  );
}
