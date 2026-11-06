import { useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Lock } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { create } from 'zustand';
import { Button, Field, Modal, Segmented, TextInput } from '../../components/ui';
import { ApiError, get, post } from '../../lib/api';
import { bridge } from '../../lib/bridge';
import { useLive } from '../../lib/live';

export type PrivateState = {
  configured: boolean;
  kind: 'pin' | 'password' | null;
  unlocked: boolean;
  blur: boolean;
  showEverywhere: boolean;
  expiresAt: number | null;
  autoLockMinutes: number;
  counts: Record<string, number>;
};

export const usePrivateUi = create<{ open: boolean; ask: () => void; close: () => void }>((set) => ({
  open: false,
  ask: () => set({ open: true }),
  close: () => set({ open: false }),
}));

export function usePrivateState() {
  return useQuery({
    queryKey: ['private', 'state'],
    queryFn: () => get<PrivateState>('/api/private/state'),
    retry: false,
  });
}

/** Global: Ctrl+L locks instantly; Windows lock/sleep locks too. */
export function usePrivateHotkeys() {
  useEffect(() => {
    const lock = () => void post('/api/private/lock').catch(() => undefined);
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
        e.preventDefault();
        lock();
        toast('Private locked');
      }
    };
    window.addEventListener('keydown', onKey);
    const off = bridge?.onSystemLock(lock);
    return () => {
      window.removeEventListener('keydown', onKey);
      off?.();
    };
  }, []);
}

export function PrivateUnlockDialog() {
  const { open, close } = usePrivateUi();
  const { data: st } = usePrivateState();
  const qc = useQueryClient();
  const [secret, setSecret] = useState('');
  const [confirm, setConfirm] = useState('');
  const [kind, setKind] = useState<'pin' | 'password'>('pin');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setup = st && !st.configured;

  useEffect(() => {
    if (!open) {
      setSecret('');
      setConfirm('');
      setErr(null);
    }
  }, [open]);

  const submit = async () => {
    setErr(null);
    if (setup) {
      if (kind === 'pin' && !/^\d{4,8}$/.test(secret)) return setErr('Use 4 to 8 digits.');
      if (kind === 'password' && secret.length < 6) return setErr('Use at least 6 characters.');
      if (secret !== confirm) return setErr("The two entries don't match.");
    } else if (!secret) {
      return setErr(st?.kind === 'password' ? 'Enter your password.' : 'Enter your PIN.');
    }
    setBusy(true);
    try {
      const next = await post<PrivateState>(setup ? '/api/private/setup' : '/api/private/unlock', { secret, kind });
      useLive.setState({ privateState: next });
      qc.invalidateQueries({ queryKey: ['private'] });
      close();
      toast.success(setup ? 'Private is set up and unlocked' : 'Private unlocked', {
        description: `It locks again after ${next.autoLockMinutes} minutes of inactivity, when Windows locks, or with Ctrl+L.`,
      });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? (st?.kind === 'password' ? 'Wrong password.' : 'Wrong PIN.') : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(v) => (v ? undefined : close())}
      width="max-w-sm"
      title={
        <span className="flex items-center gap-2">
          {setup ? <KeyRound className="size-5 text-private" /> : <Lock className="size-5 text-private" />}
          {setup ? 'Set up Private' : 'Unlock Private'}
        </span>
      }
      description={
        setup
          ? 'Choose a PIN or password. Romance, suggestive and nudity items stay hidden and blurred until you unlock.'
          : 'Private items stay hidden everywhere until you unlock.'
      }
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button variant="private" loading={busy} onClick={submit}>
            {setup ? 'Set up and unlock' : 'Unlock'}
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {setup && <Segmented value={kind} onChange={setKind} options={[{ value: 'pin', label: 'PIN' }, { value: 'password', label: 'Password' }]} />}
        <Field label={(setup ? kind : st?.kind) === 'password' ? 'Password' : 'PIN'}>
          <TextInput
            autoFocus
            type="password"
            inputMode={(setup ? kind : st?.kind) === 'password' ? 'text' : 'numeric'}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            autoComplete="off"
          />
        </Field>
        {setup && (
          <Field label="Enter it again">
            <TextInput type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          </Field>
        )}
        {err && <p className="text-[13px] text-bad">{err}</p>}
        <button type="submit" className="hidden" />
      </form>
    </Modal>
  );
}
