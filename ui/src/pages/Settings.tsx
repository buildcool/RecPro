import { Cpu, FolderCog, Info, Lock, Palette, RefreshCw, ScanText, ShieldCheck, SlidersHorizontal, Copy } from 'lucide-react';
import { type ReactNode, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button, Card, PageHeader, Segmented, Switch } from '../components/ui';
import { usePrivateUi, usePrivateState } from '../features/private/PrivateLock';
import { ModelsList } from '../features/models/ModelSetup';
import { bridge, type UpdateMode, type UpdateState } from '../lib/bridge';
import { useHealth, useSettings, useUpdateSettings } from '../lib/queries';
import { setTheme, type ThemePref } from '../lib/theme';

const SENS = [
  { value: 'never_miss', label: 'Never miss', hint: 'Asks you more often so nothing is missed' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'fewer', label: 'Fewer questions', hint: 'Asks less, may miss a few' },
] as const;

export function SettingsPage() {
  const { data: s } = useSettings();
  const { data: health } = useHealth();
  const update = useUpdateSettings();
  const priv = usePrivateState();
  const askUnlock = usePrivateUi((x) => x.ask);
  if (!s) return null;
  const set = (k: string, v: unknown) => update.mutate({ [k]: v });

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Settings" />
      <div className="mx-auto max-w-3xl space-y-5 px-6 pb-12">
        <Section icon={<Palette className="size-4" />} title="Appearance">
          <Row label="Theme">
            <Segmented
              value={s.theme}
              onChange={(v) => {
                setTheme(v as ThemePref);
                set('theme', v);
              }}
              options={[
                { value: 'system', label: 'System' },
                { value: 'light', label: 'Light' },
                { value: 'dark', label: 'Dark' },
              ]}
            />
          </Row>
        </Section>

        <Section icon={<SlidersHorizontal className="size-4" />} title="How often RecPro asks you" description="When the AI isn't sure, it asks instead of guessing. Choose how careful each area is.">
          <Row label="Faces" hint="Finding every photo of a person">
            <Segmented size="sm" value={s['sensitivity.faces'] as string} onChange={(v) => set('sensitivity.faces', v)} options={[...SENS]} />
          </Row>
          <Row label="Private content" hint="Romance, suggestive and nudity">
            <Segmented size="sm" value={s['sensitivity.sensitive'] as string} onChange={(v) => set('sensitivity.sensitive', v)} options={[...SENS]} />
          </Row>
          <Row label="Categories" hint="Activities, objects, documents, screenshots">
            <Segmented size="sm" value={s['sensitivity.categories'] as string} onChange={(v) => set('sensitivity.categories', v)} options={[...SENS]} />
          </Row>
        </Section>

        <Section icon={<Lock className="size-4" />} title="Private" description="Sensitive photos and videos stay in Private, blurred and locked.">
          <Row label="Lock" hint={priv.data?.configured ? `Locked with a ${priv.data.kind === 'password' ? 'password' : 'PIN'}` : 'Not set up yet'}>
            <Button size="sm" onClick={askUnlock}>
              {priv.data?.configured ? 'Unlock' : 'Set up'}
            </Button>
          </Row>
          <Row label="Lock again after" hint="Minutes without activity. Windows lock and Ctrl+L also lock it.">
            <Segmented
              size="sm"
              value={String(s['privacy.auto_lock_minutes'])}
              onChange={(v) => set('privacy.auto_lock_minutes', Number(v))}
              options={['1', '5', '15', '30'].map((m) => ({ value: m, label: `${m} min` }))}
            />
          </Row>
          <Row label="Blur private items by default">
            <Switch checked={!!s['privacy.blur_default']} onChange={(v) => set('privacy.blur_default', v)} label="Blur private items by default" />
          </Row>
          <Row label="Check new photos before showing them" hint="New items stay blurred until the private check has looked at them">
            <Switch checked={!!s['privacy.check_before_show']} onChange={(v) => set('privacy.check_before_show', v)} label="Check before showing" />
          </Row>
          <Row label="Treat ID documents as private" hint="Aadhaar, PAN, passport and similar">
            <Switch checked={!!s['privacy.ids_private']} onChange={(v) => set('privacy.ids_private', v)} label="Treat ID documents as private" />
          </Row>
        </Section>

        <Section icon={<Copy className="size-4" />} title="Copy and move">
          <Row label="After a verified copy, originals go to" hint="The RecPro Bin restores everything exactly with one click">
            <Segmented
              size="sm"
              value={s['ops.removal_default'] as string}
              onChange={(v) => set('ops.removal_default', v)}
              options={[
                { value: 'bin', label: 'RecPro Bin' },
                { value: 'recycle', label: 'Recycle Bin' },
                { value: 'keep', label: 'Keep' },
              ]}
            />
          </Row>
          <Row label="Folder layout at the destination">
            <Segmented
              size="sm"
              value={s['ops.structure_default'] as string}
              onChange={(v) => set('ops.structure_default', v)}
              options={[
                { value: 'keep', label: 'Same folders' },
                { value: 'flat', label: 'All together' },
                { value: 'date', label: 'Year / month' },
                { value: 'person', label: 'By person' },
              ]}
            />
          </Row>
          <Row label="If a different file has the same name">
            <Segmented
              size="sm"
              value={s['ops.conflict_default'] as string}
              onChange={(v) => set('ops.conflict_default', v)}
              options={[
                { value: 'rename', label: 'Keep both' },
                { value: 'skip', label: 'Skip it' },
              ]}
            />
          </Row>
        </Section>

        <Section icon={<ScanText className="size-4" />} title="Text in photos" description="RecPro reads the words in documents and screenshots so you can search them. ID numbers are stored with all but the last 4 characters hidden.">
          <Row label="Also read Hindi and Marathi" hint="English is always read">
            <Switch
              checked={(s['ocr.languages'] as string[] | undefined)?.includes('hi') ?? true}
              onChange={(v) => set('ocr.languages', v ? ['en', 'hi'] : ['en'])}
              label="Also read Hindi and Marathi"
            />
          </Row>
        </Section>

        <Section icon={<Cpu className="size-4" />} title="Performance">
          <Row
            label="Use the graphics card"
            hint={
              health?.gpu?.gpuPackNeeded
                ? 'Your NVIDIA card needs the GPU pack: download it under AI models below'
                : health?.gpu
                  ? `${health.gpu.name ?? health.gpu.provider}`
                  : 'Detected when recognition is set up'
            }
          >
            <Switch checked={!!s['performance.use_gpu']} onChange={(v) => set('performance.use_gpu', v)} label="Use the graphics card" />
          </Row>
          <Row label="Go easy on battery" hint="Slows analysis while the laptop is unplugged">
            <Switch checked={!!s['performance.quiet_on_battery']} onChange={(v) => set('performance.quiet_on_battery', v)} label="Go easy on battery" />
          </Row>
        </Section>

        <Section icon={<Cpu className="size-4" />} title="AI models" description="Downloaded once, then everything runs on this PC.">
          <ModelsList />
        </Section>

        <Section icon={<ShieldCheck className="size-4" />} title="Network">
          <Row
            label="Strict offline"
            hint="Blocks even the one-time AI model download. Photos, videos, faces and text never leave this PC either way."
          >
            <Switch checked={!!s['privacy.strict_offline']} onChange={(v) => set('privacy.strict_offline', v)} label="Strict offline" />
          </Row>
        </Section>

        <Section icon={<FolderCog className="size-4" />} title="Storage">
          <Row label="RecPro data folder" hint={health?.dataDir}>
            {bridge && (
              <Button
                size="sm"
                onClick={async () => {
                  const dir = await bridge!.pickFolder('Choose where RecPro keeps its index');
                  if (dir) {
                    toast('Restarting RecPro’s engine…');
                    await bridge!.setDataDir(dir);
                  }
                }}
              >
                Change…
              </Button>
            )}
          </Row>
        </Section>

        <UpdatesSection />

        <Section icon={<Info className="size-4" />} title="About">
          <Row label="RecPro" hint="Private, offline photo and video organizer">
            <span className="text-[13px] text-fg-2">Engine {health?.version}</span>
          </Row>
        </Section>
      </div>
    </div>
  );
}

const UPDATE_MODES: { value: UpdateMode; label: string; hint: string }[] = [
  { value: 'auto', label: 'Download for me', hint: 'Downloads in the background, then asks you to restart' },
  { value: 'notify', label: 'Ask me first', hint: 'Tells you what is new; you choose when to download' },
  { value: 'off', label: 'Off', hint: 'Never checks by itself' },
];

function updateStatus(u: UpdateState): string {
  switch (u.status) {
    case 'checking':
      return 'Checking…';
    case 'latest':
      return 'You have the latest version.';
    case 'available':
      return `Version ${u.latest} is available.`;
    case 'downloading':
      return `Downloading version ${u.latest}… ${u.progress}%`;
    case 'ready':
      return `Version ${u.latest} is downloaded. Restart RecPro to finish; it also installs the next time you close it.`;
    case 'error':
      return u.error ?? 'The check didn’t work.';
    default:
      return u.checkedAt ? `Last checked ${new Date(u.checkedAt).toLocaleString()}.` : 'Not checked yet.';
  }
}

function UpdatesSection() {
  const u = bridge?.updates;
  const [st, setSt] = useState<UpdateState | null>(null);
  useEffect(() => {
    if (!u) return;
    let alive = true;
    void u.get().then((s) => alive && s && setSt(s));
    const off = u.onState((s) => setSt(s));
    return () => {
      alive = false;
      off();
    };
  }, [u]);
  return (
    <Section
      icon={<RefreshCw className="size-4" />}
      title="Updates"
      description="New versions come from RecPro’s releases on GitHub. A check only asks GitHub for the latest version number: never your photos, names or text. Strict offline stops checks too."
    >
      {!u || !st ? (
        <Row label="Updates" hint="The desktop app checks for updates.">
          <span className="text-[13px] text-fg-3">Not in this window</span>
        </Row>
      ) : (
        <>
          <Row label="When a new version is out" hint={UPDATE_MODES.find((m) => m.value === st.mode)?.hint}>
            <Segmented value={st.mode} onChange={(v) => void u.setMode(v as UpdateMode).then(setSt)} options={UPDATE_MODES} />
          </Row>
          <Row label={`RecPro ${st.current}`} hint={updateStatus(st)}>
            <div className="flex gap-2">
              {st.status === 'available' && (
                <Button size="sm" variant="primary" onClick={() => void u.download().then(setSt)}>
                  {st.canInstall ? `Download ${st.latest}` : 'Open the download page'}
                </Button>
              )}
              {st.status === 'ready' && (
                <Button size="sm" variant="primary" onClick={() => void u.install()}>
                  Restart to update
                </Button>
              )}
              <Button size="sm" loading={st.status === 'checking'} disabled={st.busy || st.status === 'downloading'} onClick={() => void u.check().then(setSt)}>
                Check now
              </Button>
            </div>
          </Row>
          {st.notes && (st.status === 'available' || st.status === 'downloading' || st.status === 'ready') && (
            <div className="px-4 pb-4">
              <div className="text-[13px] font-medium">What’s new in {st.latest}</div>
              <p className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap text-[13px] text-fg-2">{st.notes}</p>
              <button type="button" className="mt-2 text-xs text-accent hover:underline" onClick={() => void u.openPage()}>
                Open the release page
              </button>
            </div>
          )}
        </>
      )}
    </Section>
  );
}

function Section({ icon, title, description, children }: { icon: ReactNode; title: string; description?: string; children: ReactNode }) {
  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center gap-2 text-[15px] font-semibold">
        <span className="text-fg-2">{icon}</span>
        {title}
      </div>
      {description && <p className="mb-2 text-[13px] text-fg-2">{description}</p>}
      <div className="divide-y divide-line">{children}</div>
    </Card>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {hint && <div className="mt-0.5 break-all text-xs text-fg-3">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
