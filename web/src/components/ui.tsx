import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { toasts, type Node } from '../api';

export function Sheet({ onClose, children }: { onClose: () => void; children: ComponentChildren }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    addEventListener('keydown', esc);
    return () => removeEventListener('keydown', esc);
  }, []);
  return (
    <div class="backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div class="sheet" role="dialog" aria-modal="true">
        <div class="grab" />
        {children}
      </div>
    </div>
  );
}

export function Toasts() {
  return (
    <div class="toasts" aria-live="polite">
      {toasts.value.map((t) => (
        <div key={t.id} class={`toast ${t.level}`}>{t.msg}</div>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ComponentChildren }) {
  return (
    <div class="field">
      <label>
        {label}
        {hint && <div class="muted" style="font-size:.8rem">{hint}</div>}
      </label>
      {children}
    </div>
  );
}

export function Stepper({ value, min, max, step = 1, unit, onChange }: {
  value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void;
}) {
  const set = (v: number) => onChange(Math.max(min, Math.min(max, v)));
  return (
    <div class="stepper">
      <button aria-label="less" onClick={() => set(value - step)} disabled={value <= min}>−</button>
      <span class="num">{value}{unit ? ` ${unit}` : ''}</span>
      <button aria-label="more" onClick={() => set(value + step)} disabled={value >= max}>+</button>
    </div>
  );
}

export function Segmented({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <div class="seg" role="radiogroup">
      {options.map((o) => (
        <button key={o} role="radio" aria-checked={o === value} class={o === value ? 'on' : ''} onClick={() => onChange(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ value, onChange, label }: { value: boolean; onChange: (v: boolean) => void; label?: string }) {
  return <button class={`switch ${value ? 'on' : ''}`} role="switch" aria-checked={value} aria-label={label} onClick={() => onChange(!value)} />;
}

export function Battery({ node }: { node: Node }) {
  if (node.virtual) return <span class="muted">sim</span>;
  if (node.batt_pct === undefined) return <span class="muted">USB</span>;
  const low = node.batt_pct < 20;
  return <span class={`batt ${low ? 'low' : ''}`}>{low ? '⚠ ' : ''}{node.batt_pct}%</span>;
}

// Mirrors the target's LED; effect 0 = off
export function Tile({ node, flash, onClick }: { node: Node; flash?: boolean; onClick?: () => void }) {
  const lit = node.online && node.led && node.led.e !== 0 && node.led.c !== '#000000';
  const style = lit ? `background:${node.led.c};color:#000;border-color:${node.led.c}` : '';
  return (
    <button class={`tile ${node.online ? '' : 'off'} ${flash ? 'flash' : ''}`} style={style} onClick={onClick}
      aria-label={`Target ${node.slot}${node.online ? '' : ', offline'}`}>
      {node.slot}
      {node.virtual && <span class="sim">SIM</span>}
    </button>
  );
}

// A button that must be held (prevents accidental stops)
export function HoldButton({ ms = 800, onDone, children, cls = 'btn danger' }: {
  ms?: number; onDone: () => void; children: ComponentChildren; cls?: string;
}) {
  const [held, setHeld] = useState(false);
  const timer = useRef<number>();
  const start = () => {
    setHeld(true);
    timer.current = window.setTimeout(() => {
      setHeld(false);
      onDone();
    }, ms);
  };
  const cancel = () => {
    setHeld(false);
    clearTimeout(timer.current);
  };
  return (
    <button class={`${cls} hold`} onPointerDown={start} onPointerUp={cancel} onPointerLeave={cancel} onContextMenu={(e) => e.preventDefault()}>
      <span class="fill" style={held ? `transform:scaleX(1);transition:transform ${ms}ms linear` : ''} />
      {children}
    </button>
  );
}

const paths: Record<string, string> = {
  play: 'M8 5v14l11-7z',
  targets: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm0 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
  scores: 'M7 21h10M12 17v4M6 3h12v4a6 6 0 0 1-12 0zM6 5H3a3 3 0 0 0 3 4M18 5h3a3 3 0 0 1-3 4',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
};

export function Icon({ name }: { name: keyof typeof paths }) {
  const filled = name === 'play' || name === 'targets';
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill={filled ? 'currentColor' : 'none'} stroke={filled ? 'none' : 'currentColor'}
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill-rule="evenodd">
      <path d={paths[name]} />
    </svg>
  );
}

export function fmtMs(ms?: number) {
  if (ms === undefined || ms === null) return '–';
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms} ms`;
}

export function fmtTime(s?: number) {
  if (s === undefined) return '–';
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}
