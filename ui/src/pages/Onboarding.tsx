import { useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';
import { ArrowLeft, ArrowRight, Check, FolderOpen, FolderPlus, HardDrive, Lock, MessageCircleQuestion, ShieldCheck, Undo2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Button, Card } from '../components/ui';
import { addFolders, pickFolders } from '../features/library/addFolders';
import { FolderBrowserDialog } from '../features/library/FolderBrowser';
import { get, patch, qs } from '../lib/api';
import { bridge } from '../lib/bridge';
import { bytes, num } from '../lib/format';
import { useFolders, useHealth } from '../lib/queries';

const STEPS = ['Welcome', 'Your folders', 'Storage', 'Ready'] as const;

function savedStep(): number {
  try {
    return Number(sessionStorage.getItem('recpro.onboarding.step') || 0);
  } catch {
    return 0;
  }
}

export function OnboardingPage() {
  const [step, setStep] = useState(savedStep);
  const nav = useNavigate();
  const qc = useQueryClient();
  useEffect(() => {
    try {
      sessionStorage.setItem('recpro.onboarding.step', String(step));
    } catch {
      /* ignore */
    }
  }, [step]);

  const finish = async () => {
    await patch('/api/settings', { onboarded: true });
    await qc.invalidateQueries({ queryKey: ['settings'] });
    try {
      sessionStorage.removeItem('recpro.onboarding.step');
    } catch {
      /* ignore */
    }
    nav('/', { replace: true });
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-canvas">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-10">
        <div className="mb-8 flex items-center gap-3">
          <img src="./icon.png" alt="" className="size-9 rounded-xl" />
          <span className="text-lg font-semibold tracking-tight">RecPro</span>
          <ol className="ml-auto flex items-center gap-2 text-xs text-fg-3" aria-label="Setup steps">
            {STEPS.map((s, i) => (
              <li key={s} className={clsx('flex items-center gap-1.5', i === step && 'font-medium text-fg')}>
                <span
                  className={clsx(
                    'flex size-5 items-center justify-center rounded-full text-[11px]',
                    i < step ? 'bg-ok text-white' : i === step ? 'bg-accent text-accent-fg' : 'bg-surface-3',
                  )}
                >
                  {i < step ? <Check className="size-3" /> : i + 1}
                </span>
                <span className="hidden sm:inline">{s}</span>
              </li>
            ))}
          </ol>
        </div>
        {step === 0 && <Welcome next={() => setStep(1)} />}
        {step === 1 && <AddFoldersStep back={() => setStep(0)} next={() => setStep(2)} />}
        {step === 2 && <StorageStep back={() => setStep(1)} next={() => setStep(3)} />}
        {step === 3 && <ReadyStep back={() => setStep(2)} finish={() => void finish().catch((e) => toast.error(String(e)))} />}
      </div>
      <FolderBrowserDialog />
    </div>
  );
}

function Welcome({ next }: { next: () => void }) {
  const promises = [
    { icon: ShieldCheck, title: 'Nothing leaves this PC', body: 'Faces, photos, videos and text are analyzed on this computer. Nothing is uploaded, ever.' },
    { icon: MessageCircleQuestion, title: 'It asks when it isn’t sure', body: 'Instead of guessing, RecPro asks you about doubtful matches, so nothing is missed.' },
    { icon: Undo2, title: 'It never loses a file', body: 'Every copy is checked byte for byte before anything is removed, and everything can be undone.' },
    { icon: Lock, title: 'Private stays private', body: 'Romance, suggestive and nudity content is kept in a locked, blurred Private section.' },
  ];
  return (
    <div className="flex flex-1 flex-col">
      <h1 className="text-[30px] font-semibold leading-tight tracking-tight">Find every photo of anyone, privately.</h1>
      <p className="mt-3 max-w-2xl text-[15px] text-fg-2">
        RecPro organizes the photos and videos already on your computer. Point it at your folders, pick a person or a kind of photo, and it finds them all.
      </p>
      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {promises.map((p) => (
          <Card key={p.title} className="p-4">
            <p.icon className="size-5 text-accent" />
            <div className="mt-2 text-[15px] font-semibold">{p.title}</div>
            <p className="mt-1 text-[13px] text-fg-2">{p.body}</p>
          </Card>
        ))}
      </div>
      <div className="mt-auto flex justify-end pt-10">
        <Button variant="primary" size="lg" onClick={next}>
          Get started <ArrowRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}

function AddFoldersStep({ back, next }: { back: () => void; next: () => void }) {
  const { data: folders } = useFolders();
  const [dragOver, setDragOver] = useState(false);
  const choose = async () => {
    try {
      await addFolders(await pickFolders());
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <div className="flex flex-1 flex-col">
      <h1 className="text-[26px] font-semibold tracking-tight">Where are your photos and videos?</h1>
      <p className="mt-2 text-[15px] text-fg-2">Add Pictures, a phone backup, WhatsApp media, an external drive… Files stay exactly where they are.</p>
      <button
        type="button"
        onClick={() => void choose()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const paths = [...e.dataTransfer.files].map((f) => bridge?.pathForFile(f) ?? '').filter(Boolean);
          void addFolders(paths);
        }}
        className={clsx(
          'mt-6 flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors',
          dragOver ? 'border-accent bg-accent-soft' : 'border-line-strong hover:border-accent hover:bg-surface',
        )}
      >
        <FolderPlus className="size-8 text-accent" />
        <span className="text-[15px] font-semibold">Choose folders</span>
        <span className="text-[13px] text-fg-2">or drag folders here</span>
      </button>
      <div className="mt-5 space-y-2">
        {folders?.map((f) => (
          <div key={f.id} className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
            <FolderOpen className="size-5 text-accent" />
            <span className="min-w-0 flex-1 truncate text-sm font-medium" title={f.path}>
              {f.path}
            </span>
            <span className="text-[13px] text-fg-2">{f.status === 'scanning' ? 'Counting…' : `${num(f.photos)} photos · ${num(f.videos)} videos`}</span>
          </div>
        ))}
      </div>
      <div className="mt-auto flex justify-between pt-10">
        <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={back}>
          Back
        </Button>
        <Button variant="primary" size="lg" onClick={next}>
          {folders?.length ? 'Continue' : 'Skip for now'} <ArrowRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}

function StorageStep({ back, next }: { back: () => void; next: () => void }) {
  const { data: health } = useHealth();
  const [free, setFree] = useState<number | null>(null);
  useEffect(() => {
    if (!health?.dataDir) return;
    get<{ free: number }>(`/api/fs/free${qs({ path: health.dataDir })}`)
      .then((r) => setFree(r.free))
      .catch(() => setFree(null));
  }, [health?.dataDir]);
  return (
    <div className="flex flex-1 flex-col">
      <h1 className="text-[26px] font-semibold tracking-tight">Where should RecPro keep its index?</h1>
      <p className="mt-2 text-[15px] text-fg-2">
        Thumbnails, what RecPro learns about faces and categories, and your answers are stored here. Plan for about 3 to 5% of your library's size. Your
        photos are not copied here.
      </p>
      <Card className="mt-6 flex flex-wrap items-center gap-4 p-5">
        <HardDrive className="size-6 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-semibold">{health?.dataDir ?? '…'}</div>
          <div className="text-[13px] text-fg-2">{free != null ? `${bytes(free)} free on this drive` : ' '}</div>
        </div>
        {bridge && (
          <Button
            onClick={async () => {
              const dir = await bridge!.pickFolder('Choose where RecPro keeps its index');
              if (dir) {
                toast('Moving RecPro’s index location…');
                await bridge!.setDataDir(dir);
              }
            }}
          >
            Change…
          </Button>
        )}
      </Card>
      <div className="mt-auto flex justify-between pt-10">
        <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={back}>
          Back
        </Button>
        <Button variant="primary" size="lg" onClick={next}>
          Continue <ArrowRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}

function ReadyStep({ back, finish }: { back: () => void; finish: () => void }) {
  return (
    <div className="flex flex-1 flex-col">
      <h1 className="text-[26px] font-semibold tracking-tight">You're set</h1>
      <p className="mt-2 text-[15px] text-fg-2">
        Your photos appear within seconds. Faces, categories and text are analyzed in the background. You can keep using RecPro while it works, and pause it
        any time from the bar at the bottom.
      </p>
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {[
          ['Name your people', 'RecPro groups faces. Give the groups names to search by person.'],
          ['Answer quick questions', 'When it isn’t sure, it asks. Each answer teaches it.'],
          ['Find and move', 'Pick someone, check the matches, copy them anywhere.'],
        ].map(([t, b]) => (
          <Card key={t} className="p-4">
            <div className="text-[15px] font-semibold">{t}</div>
            <p className="mt-1 text-[13px] text-fg-2">{b}</p>
          </Card>
        ))}
      </div>
      <div className="mt-auto flex justify-between pt-10">
        <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={back}>
          Back
        </Button>
        <Button variant="primary" size="lg" onClick={finish}>
          Open RecPro <ArrowRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
