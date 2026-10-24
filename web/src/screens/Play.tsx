import { useEffect, useState } from 'preact/hooks';
import { loadModes, loadPlayers, modes, online, players, post, safeMode, toast, type ModeSchema } from '../api';
import { Field, Segmented, Sheet, Stepper, Toggle } from '../components/ui';
import { unlockAudio } from '../sound';

const LAST_PLAYER = 'targets.player';
const LAST_CFG = 'targets.cfg.';

function load<T>(key: string, def: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : def;
  } catch {
    return def;
  }
}
function save(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* private mode */
  }
}

function PlayerPicker({ value, onChange }: { value: number; onChange: (id: number) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const add = async () => {
    const r = await post('/api/v1/players?action=add', { name: name.trim(), color: players.value.length % 8 });
    if (r.ok) {
      await loadPlayers();
      onChange(r.id as number);
      setAdding(false);
      setName('');
    }
  };
  if (adding) {
    return (
      <div class="row">
        <input type="text" placeholder="Player name" maxLength={20} value={name} autoFocus
          onInput={(e) => setName((e.target as HTMLInputElement).value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button class="btn primary" onClick={add} disabled={!name.trim()}>Add</button>
        <button class="btn ghost" onClick={() => setAdding(false)}>✕</button>
      </div>
    );
  }
  return (
    <div class="row">
      <select value={value} onChange={(e) => onChange(Number((e.target as HTMLSelectElement).value))} aria-label="Player">
        <option value={0}>Guest</option>
        {players.value.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <button class="btn" onClick={() => setAdding(true)}>+ New</button>
    </div>
  );
}

function ModeSheet({ mode, player, onClose }: { mode: ModeSchema; player: number; onClose: () => void }) {
  const defaults = Object.fromEntries(mode.settings.map((s) => [s.key, s.def]));
  const [cfg, setCfg] = useState<Record<string, unknown>>({ ...defaults, ...load(LAST_CFG + mode.id, {}) });
  const [rules, setRules] = useState(false);
  const [busy, setBusy] = useState(false);
  const enough = online.value.length >= mode.min_nodes;

  const start = async (force = false) => {
    unlockAudio();
    setBusy(true);
    const r = await post('/api/v1/game/start', { mode: mode.id, settings: cfg, player, force });
    setBusy(false);
    if (r.confirm) {
      if (confirm(r.msg || 'Start anyway?')) start(true);
      return;
    }
    if (r.ok) {
      save(LAST_CFG + mode.id, cfg);
      onClose();
    }
  };

  return (
    <Sheet onClose={onClose}>
      <h1>{mode.name}</h1>
      <p class="muted">{mode.tagline}</p>
      {Object.keys(mode.presets).length > 0 && (
        <div class="chips" style="margin:12px 0">
          {Object.entries(mode.presets).map(([name, p]) => (
            <button key={name} class="chip" onClick={() => setCfg({ ...defaults, ...p })}>{name}</button>
          ))}
        </div>
      )}
      <div class="card">
        {mode.settings.map((s) => (
          <Field key={s.key} label={s.label}>
            {s.type === 'int' && (
              <Stepper value={Number(cfg[s.key])} min={s.min!} max={s.max!} unit={s.unit}
                onChange={(v) => setCfg({ ...cfg, [s.key]: v })} />
            )}
            {s.type === 'enum' && (
              <Segmented value={String(cfg[s.key])} options={s.options!} onChange={(v) => setCfg({ ...cfg, [s.key]: v })} />
            )}
            {s.type === 'bool' && (
              <Toggle value={Boolean(cfg[s.key])} label={s.label} onChange={(v) => setCfg({ ...cfg, [s.key]: v })} />
            )}
          </Field>
        ))}
      </div>
      <button class="btn ghost block" style="margin-top:8px" onClick={() => setRules(!rules)} aria-expanded={rules}>
        {rules ? '▾' : '▸'} How to play
      </button>
      {rules && (
        <ul class="muted" style="margin:0 0 8px;padding-left:20px">
          {mode.rules.map((r) => <li key={r} style="margin-bottom:6px">{r}</li>)}
        </ul>
      )}
      <p class={enough ? 'muted' : ''} style={enough ? '' : 'color:var(--danger);font-weight:600'}>
        {online.value.length} target{online.value.length === 1 ? '' : 's'} online
        {enough ? ' ✓' : ` — this mode needs at least ${mode.min_nodes}`}
      </p>
      <button class="btn primary big block" disabled={!enough || busy || safeMode.value} onClick={() => start()}>
        {busy ? 'Starting…' : 'START'}
      </button>
    </Sheet>
  );
}

export function Play() {
  const [player, setPlayer] = useState<number>(load(LAST_PLAYER, 0));
  const [open, setOpen] = useState<ModeSchema | null>(null);
  useEffect(() => {
    if (!modes.value.length) loadModes();
    loadPlayers();
  }, []);
  const pick = (id: number) => {
    setPlayer(id);
    save(LAST_PLAYER, id);
  };
  return (
    <div class="page stack">
      {safeMode.value && <div class="card" style="border-color:var(--danger)">Safe mode: the hub restarted after repeated crashes. Games are off; update or restart the hub in Settings.</div>}
      <section>
        <h3>Who's shooting?</h3>
        <PlayerPicker value={player} onChange={pick} />
      </section>
      <section>
        <h3>Game</h3>
        {!modes.value.length && <div class="empty">Loading games…</div>}
        <div class="grid2 wide">
          {modes.value.map((m) => {
            const locked = online.value.length < m.min_nodes;
            return (
              <button key={m.id} class={`card mode-card ${locked ? 'locked' : ''}`}
                onClick={() => (locked ? toast(`${m.name} needs ${m.min_nodes} targets online`, 'warn') : setOpen(m))}>
                <b>{m.name}</b>
                <small>{m.tagline}</small>
                {m.min_nodes > 1 && <small>{m.min_nodes}+ targets</small>}
              </button>
            );
          })}
        </div>
      </section>
      {open && <ModeSheet mode={open} player={player} onClose={() => setOpen(null)} />}
    </div>
  );
}
