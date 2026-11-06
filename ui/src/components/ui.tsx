import * as DialogP from '@radix-ui/react-dialog';
import * as SwitchP from '@radix-ui/react-switch';
import * as TooltipP from '@radix-ui/react-tooltip';
import { clsx } from 'clsx';
import { Loader2, X } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';

// ---- Button -----------------------------------------------------------------
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'private' | 'soft';
type Size = 'xs' | 'sm' | 'md' | 'lg';

const variants: Record<Variant, string> = {
  primary: 'bg-accent text-accent-fg hover:bg-accent/90 active:bg-accent/85',
  secondary: 'bg-surface border border-line-strong text-fg hover:bg-surface-2',
  ghost: 'text-fg-2 hover:bg-surface-2 hover:text-fg',
  soft: 'bg-accent-soft text-accent-text hover:bg-accent-soft/70',
  danger: 'bg-bad text-white hover:bg-bad/90',
  private: 'bg-private text-white hover:bg-private/90',
};
const sizes: Record<Size, string> = {
  xs: 'h-7 px-2 text-xs gap-1.5 rounded-md',
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-9 px-3.5 text-sm gap-2 rounded-lg',
  lg: 'h-11 px-5 text-[15px] gap-2 rounded-xl',
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  loading?: boolean;
  ref?: Ref<HTMLButtonElement>;
};

export function Button({ variant = 'secondary', size = 'md', icon, loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={clsx(
        'inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-medium transition-colors',
        'disabled:pointer-events-none disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className,
  size = 'md',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; size?: 'sm' | 'md'; ref?: Ref<HTMLButtonElement> }) {
  return (
    <Tip label={label}>
      <button
        type="button"
        aria-label={label}
        className={clsx(
          'inline-flex items-center justify-center rounded-lg text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-40',
          size === 'sm' ? 'size-7' : 'size-9',
          className,
        )}
        {...rest}
      />
    </Tip>
  );
}

// ---- Tooltip ----------------------------------------------------------------
export function Tip({ label, children, side = 'bottom' }: { label: ReactNode; children: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  return (
    <TooltipP.Root delayDuration={350}>
      <TooltipP.Trigger asChild>{children}</TooltipP.Trigger>
      <TooltipP.Portal>
        <TooltipP.Content
          side={side}
          sideOffset={6}
          className="z-[100] max-w-xs rounded-md bg-fg px-2 py-1 text-xs text-canvas shadow-pop"
        >
          {label}
        </TooltipP.Content>
      </TooltipP.Portal>
    </TooltipP.Root>
  );
}

export const TooltipProvider = TooltipP.Provider;

// ---- Switch -----------------------------------------------------------------
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  tone = 'accent',
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
  disabled?: boolean;
  tone?: 'accent' | 'private';
}) {
  return (
    <SwitchP.Root
      checked={checked}
      onCheckedChange={onChange}
      disabled={disabled}
      aria-label={label}
      className={clsx(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-surface-3 transition-colors disabled:opacity-50',
        tone === 'private' ? 'data-[state=checked]:bg-private' : 'data-[state=checked]:bg-accent',
      )}
    >
      <SwitchP.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </SwitchP.Root>
  );
}

// ---- Badge ------------------------------------------------------------------
type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'bad' | 'private';
const tones: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-fg-2',
  accent: 'bg-accent-soft text-accent-text',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  private: 'bg-private-soft text-private',
};

export function Badge({ tone = 'neutral', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium', tones[tone], className)}>
      {children}
    </span>
  );
}

// ---- Progress ---------------------------------------------------------------
export function Progress({ value, tone = 'accent', className }: { value: number; tone?: 'accent' | 'ok' | 'warn' | 'private'; className?: string }) {
  const color = { accent: 'bg-accent', ok: 'bg-ok', warn: 'bg-warn', private: 'bg-private' }[tone];
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-surface-3', className)}>
      <div className={clsx('h-full rounded-full transition-[width] duration-500', color)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

// ---- Misc -------------------------------------------------------------------
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface px-1 font-sans text-[11px] text-fg-2">
      {children}
    </kbd>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('size-4 animate-spin text-fg-3', className)} />;
}

export function EmptyState({
  icon,
  title,
  body,
  actions,
  className,
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx('mx-auto flex max-w-md flex-col items-center px-6 py-16 text-center', className)}>
      {icon && <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-surface-2 text-fg-2">{icon}</div>}
      <h2 className="text-[17px] font-semibold text-fg">{title}</h2>
      {body && <div className="mt-1.5 text-sm leading-relaxed text-fg-2">{body}</div>}
      {actions && <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx('rounded-2xl border border-line bg-surface', className)}>{children}</div>;
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = 'md',
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; hint?: string }[];
  size?: 'sm' | 'md';
}) {
  return (
    <div role="radiogroup" className="inline-flex rounded-lg bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          title={o.hint}
          onClick={() => onChange(o.value)}
          className={clsx(
            'rounded-md font-medium transition-colors',
            size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
            value === o.value ? 'bg-surface text-fg shadow-sm' : 'text-fg-2 hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---- Modal ------------------------------------------------------------------
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width = 'max-w-lg',
  dismissable = true,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: string;
  dismissable?: boolean;
}) {
  return (
    <DialogP.Root open={open} onOpenChange={(v) => (dismissable || v ? onOpenChange(v) : undefined)}>
      <DialogP.Portal>
        <DialogP.Overlay className="fixed inset-0 z-50 bg-overlay" />
        <DialogP.Content
          onEscapeKeyDown={(e) => !dismissable && e.preventDefault()}
          onPointerDownOutside={(e) => !dismissable && e.preventDefault()}
          className={clsx(
            'fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border border-line bg-surface shadow-pop',
            width,
          )}
        >
          <div className="flex items-start gap-3 px-5 pt-5">
            <div className="min-w-0 flex-1">
              <DialogP.Title className="text-[16px] font-semibold text-fg">{title}</DialogP.Title>
              {description ? (
                <DialogP.Description className="mt-1 text-sm text-fg-2">{description}</DialogP.Description>
              ) : (
                <DialogP.Description className="sr-only">{typeof title === 'string' ? title : 'Dialog'}</DialogP.Description>
              )}
            </div>
            {dismissable && (
              <DialogP.Close className="-mr-1 -mt-1 rounded-lg p-1.5 text-fg-3 hover:bg-surface-2 hover:text-fg" aria-label="Close">
                <X className="size-4" />
              </DialogP.Close>
            )}
          </div>
          {children && <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>}
          {footer && <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </DialogP.Content>
      </DialogP.Portal>
    </DialogP.Root>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-fg">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-fg-3">{hint}</span>}
    </label>
  );
}

export function TextInput({ className, ...rest }: React.InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return (
    <input
      className={clsx(
        'h-9 w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg placeholder:text-fg-3',
        'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20',
        className,
      )}
      {...rest}
    />
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-[15px] font-semibold text-fg">{children}</h2>
      {right}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 px-6 pb-4 pt-5">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <div className="mt-0.5 text-sm text-fg-2">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
