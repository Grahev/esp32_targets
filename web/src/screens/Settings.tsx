import { useEffect, useState } from 'preact/hooks';
import { fw, get, nodes, ota, post, settings, toast, type Settings as S } from '../api';
import { Field, Segmented, Stepper, Toggle } from '../components/ui';

const THEME = 'targets.theme';

export function applyTheme() {
  let t = 'dark';
  try {
    t = localStorage.getItem(THEME) || 'dark';
  } catch {
    /* default */
  }
  document.documentElement.dataset.theme = t;
}

function upload(url: string, file: File, onPct: (p: number) => void): Promise<{ ok: boolean; msg?: string }> {
  return new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('POST', url);
    x.upload.onprogress = (e) => e.lengthComputable && onPct(Math.round((e.loaded / e.total) * 100));
    x.onload = () => {
      let j: { msg?: string } = {};
      try {
        j = JSON.parse(x.responseText);
      } catch {
        /* empty */
      }
      resolve({ ok: x.status < 300, msg: j.msg });
    };
    x.onerror = () => resolve({ ok: false, msg: 'Upload failed' });
    const fd = new FormData();
    fd.append('file', file, file.name);
    x.send(fd);
  });
}

async function restore(file: File) {
  let b: any;
  try {
    b = JSON.parse(await file.text());
  } catch {
    return toast('That file is not a backup', 'error');
  }
  if (b.format !== 'targets-backup') return toast('That file is not a Targets backup', 'error');
  if (!confirm('Replace the settings, targets, players and scores on the hub with this backup?')) return;
  const part = async (name: string, body: string) => {
    const r = await fetch(`/api/v1/restore?part=${encodeURIComponent(name)}`, { method: 'POST', body });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).msg || name);
  };
  try {
    if (b.settings) await part('settings', JSON.stringify(b.settings));
    if (b.nodes) await part('nodes', JSON.stringify(b.nodes));
    if (b.players) await part('players', JSON.stringify(b.players));
    for (const [mode, rows] of Object.entries(b.scores || {})) await part(`scores/${mode}`, JSON.stringify(rows));
    const lines = (b.history || []).filter(Boolean).map((e: unknown) => JSON.stringify(e)).join('\n');
    if (lines) await part('history', lines + '\n');
    await post('/api/v1/reboot');
    toast('Backup restored. The hub is restarting; reconnect in a few seconds.');
  } catch (e) {
    toast(`Restore failed: ${(e as Error).message}`, 'error');
  }
}

export function Settings({ onWizard }: { onWizard: () => void }) {
  const s = settings.value;
  const [draft, setDraft] = useState<Partial<S> & { password?: string }>({});
  const [pass, setPass] = useState('');
  const [hubPct, setHubPct] = useState<number | null>(null);
  const [nodePct, setNodePct] = useState<number | null>(null);
  const [nodeFw, setNodeFw] = useState(false);
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || 'dark');
  useEffect(() => setDraft({}), [s]);
  if (!s) return <div class="page empty">Connecting…</div>;
  const v = { ...s, ...draft };
  const dirty = Object.keys(draft).length > 0;
  const saveAll = async () => {
    const wifi = draft.name !== undefined || draft.channel !== undefined;
    if (wifi && !confirm('Changing the WiFi name or channel restarts the network. Your phone must reconnect. Continue?')) return;
    if ((await post('/api/v1/settings', draft)).ok) setDraft({});
  };
  const setPassword = async (clear: boolean) => {
    const p = clear ? '' : pass;
    if (!clear && p.length < 8) return toast('Use at least 8 characters', 'warn');
    if (!confirm(clear ? 'Remove the WiFi password (open network)?' : 'Set this WiFi password? Your phone must reconnect with it.')) return;
    if ((await post('/api/v1/settings', { password: p })).ok) setPass('');
  };
  const set = (k: keyof S, val: unknown) => setDraft({ ...draft, [k]: val });
  const pickTheme = (t: string) => {
    setTheme(t);
    try {
      localStorage.setItem(THEME, t);
    } catch {
      /* ignore */
    }
    applyTheme();
  };
  const hubUpdate = async (f: File) => {
    if (!confirm(`Install ${f.name} on the hub? It restarts when done.`)) return;
    setHubPct(0);
    const r = await upload('/api/v1/ota/hub', f, setHubPct);
    setHubPct(null);
    toast(r.msg || (r.ok ? 'Installed' : 'Failed'), r.ok ? 'info' : 'error');
  };
  const nodeUpload = async (f: File) => {
    setNodePct(0);
    const r = await upload('/api/v1/ota/node', f, setNodePct);
    setNodePct(null);
    setNodeFw(r.ok);
    if (!r.ok) toast(r.msg || 'Not a target firmware file', 'error');
  };
  const pushNodes = () => {
    const macs = nodes.value.filter((n) => n.online && !n.virtual).map((n) => n.mac);
    post('/api/v1/ota/node/start', { macs });
  };
  const o = ota.value;

  return (
    <div class="page">
      <h1>Settings</h1>

      <div class="section">
        <h3>WiFi</h3>
        <div class="card">
          <Field label="Network name">
            <input type="text" maxLength={31} value={v.name} style="max-width:200px" onInput={(e) => set('name', (e.target as HTMLInputElement).value)} />
          </Field>
          <Field label="Channel" hint="Try 6 or 11 if the field is busy">
            <Segmented value={String(v.channel)} options={['1', '6', '11']} onChange={(c) => set('channel', Number(c))} />
          </Field>
          <Field label="Password" hint={s.has_password ? 'Protected (WPA2)' : 'Open network: anyone nearby can join'}>
            <span />
          </Field>
          <div class="row" style="padding-bottom:12px">
            <input type="password" placeholder={s.has_password ? 'New password' : 'Set a password (8+)'} value={pass}
              onInput={(e) => setPass((e.target as HTMLInputElement).value)} autoComplete="new-password" />
            <button class="btn" onClick={() => setPassword(false)} disabled={!pass}>Set</button>
            {s.has_password && <button class="btn ghost" onClick={() => setPassword(true)}>Remove</button>}
          </div>
        </div>
      </div>

      <div class="section">
        <h3>Targets</h3>
        <div class="card">
          <Field label="LED brightness"><Stepper value={v.brightness} min={10} max={255} step={15} onChange={(x) => set('brightness', x)} /></Field>
          <Field label="Add new targets automatically"><Toggle value={v.auto_accept} onChange={(x) => set('auto_accept', x)} /></Field>
          <Field label="Maximum targets"><Stepper value={v.max_nodes} min={1} max={8} onChange={(x) => set('max_nodes', x)} /></Field>
        </div>
      </div>

      <div class="section">
        <h3>This phone</h3>
        <div class="card">
          <Field label="Sounds"><Toggle value={v.sounds} onChange={(x) => set('sounds', x)} /></Field>
          <Field label="Theme" hint="Light is easier to read in sunlight">
            <Segmented value={theme === 'light' ? 'Light' : 'Dark'} options={['Dark', 'Light']} onChange={(t) => pickTheme(t.toLowerCase())} />
          </Field>
        </div>
      </div>

      <div class="section">
        <h3>Simulated targets</h3>
        <div class="card">
          <Field label="Simulated targets" hint="For trying modes with more targets than you have">
            <Stepper value={v.virtual_nodes} min={0} max={8} onChange={(x) => set('virtual_nodes', x)} />
          </Field>
          <Field label="They shoot themselves" hint="Off: tap their tiles during a game">
            <Toggle value={v.virtual_autoshoot} onChange={(x) => set('virtual_autoshoot', x)} />
          </Field>
        </div>
      </div>

      {dirty && <button class="btn primary big block" style="position:sticky;bottom:80px;margin-top:16px" onClick={saveAll}>Save changes</button>}

      <div class="section">
        <h3>Updates</h3>
        <div class="card stack">
          <p>Hub firmware <b class="num">{fw.value}</b></p>
          <label class="btn block">
            {hubPct !== null ? `Uploading ${hubPct}%…` : 'Install hub update (.bin)'}
            <input type="file" accept=".bin" hidden onChange={(e) => {
              const f = (e.target as HTMLInputElement).files?.[0];
              if (f) hubUpdate(f);
            }} />
          </label>
          <label class="btn block">
            {nodePct !== null ? `Uploading ${nodePct}%…` : 'Upload target firmware (.bin)'}
            <input type="file" accept=".bin" hidden onChange={(e) => {
              const f = (e.target as HTMLInputElement).files?.[0];
              if (f) nodeUpload(f);
            }} />
          </label>
          {nodeFw && !o?.active && <button class="btn primary block" onClick={pushNodes}>Update all online targets</button>}
          {o && (
            <p class="num">
              {o.active ? `Target ${o.slot}: ${o.phase} ${o.pct ?? 0}% · ` : 'Finished · '}
              {o.done.length} updated, {o.failed.length} failed of {o.total}
            </p>
          )}
        </div>
      </div>

      <div class="section">
        <h3>Data</h3>
        <div class="card stack">
          <a class="btn block" href="/api/v1/backup" download="targets-backup.json">Download backup</a>
          <label class="btn block">
            Restore backup
            <input type="file" accept=".json,application/json" hidden onChange={(e) => {
              const f = (e.target as HTMLInputElement).files?.[0];
              if (f) restore(f);
            }} />
          </label>
          <p class="muted" style="font-size:.85rem">Moving from v1? Restore the file made by tools/migrate_v1.py.</p>
        </div>
      </div>

      <div class="section">
        <h3>Advanced</h3>
        <div class="card stack">
          <button class="btn block" onClick={onWizard}>Run setup again</button>
          <button class="btn block" onClick={async () => setDiag(await get('/api/v1/diag'))}>Diagnostics</button>
          {diag && <pre class="num" style="white-space:pre-wrap;font-size:.8rem">{JSON.stringify(diag, null, 1)}</pre>}
          <button class="btn block" onClick={() => confirm('Restart the hub?') && post('/api/v1/reboot')}>Restart hub</button>
          <button class="btn danger block" onClick={() => {
            const c = prompt('This erases all settings, targets, players and scores. Type RESET to confirm.');
            if (c) post('/api/v1/factory_reset', { confirm: c });
          }}>Factory reset</button>
        </div>
      </div>
    </div>
  );
}
