import { useState } from 'preact/hooks';
import { nodes, pending, post, settings, taps } from '../api';
import { Tile } from '../components/ui';

// First run: name the system, (optionally) protect the WiFi, add targets, test them.
export function Wizard({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState(settings.value?.name || 'Airsoft-Master');
  const [pass, setPass] = useState('');
  const [testFrom, setTestFrom] = useState(0);  // hits after this time count as tested
  const isTested = (slot: number) => (taps.value[slot] || 0) > testFrom;
  const tested = nodes.value.filter((n) => isTested(n.slot)).length;

  const finish = async (wifi: boolean) => {
    const body: Record<string, unknown> = { wizard_done: true };
    if (wifi) {
      if (name !== settings.value?.name) body.name = name;
      if (pass) body.password = pass;
    }
    if ((await post('/api/v1/settings', body)).ok) onDone();
  };

  return (
    <div class="page stack" style="padding-bottom:24px">
      <p class="muted">Setup · step {step + 1} of 3</p>
      {step === 0 && (
        <>
          <h1>Welcome</h1>
          <p>Let's get your targets ready. This takes about two minutes.</p>
          <div class="card stack">
            <label>System name (also the WiFi name)
              <input type="text" maxLength={31} value={name} onInput={(e) => setName((e.target as HTMLInputElement).value)} />
            </label>
            <label>WiFi password <span class="muted">(optional, 8+ characters)</span>
              <input type="password" value={pass} autoComplete="new-password" placeholder="Leave empty for an open network"
                onInput={(e) => setPass((e.target as HTMLInputElement).value)} />
            </label>
            <p class="muted" style="font-size:.85rem">Name and password are applied at the end; your phone will reconnect then.</p>
          </div>
          <button class="btn primary big block" disabled={!name || (pass.length > 0 && pass.length < 8)} onClick={() => setStep(1)}>Next</button>
        </>
      )}
      {step === 1 && (
        <>
          <h1>Switch on your targets</h1>
          <p>Each target's light breathes white while it looks for the hub, then turns dim blue once connected.</p>
          <div class="card">
            {nodes.value.length === 0 && <p class="muted">Waiting for targets…</p>}
            <div class="tiles">{nodes.value.map((n) => <Tile key={n.mac} node={n} />)}</div>
            {pending.value.length > 0 && <p style="margin-top:12px">{pending.value.length} more waiting to be added on the Targets screen.</p>}
          </div>
          <button class="btn primary big block" disabled={!nodes.value.length} onClick={() => {
            setTestFrom(Date.now());
            setStep(2);
          }}>
            {nodes.value.length ? `Continue with ${nodes.value.length} target${nodes.value.length > 1 ? 's' : ''}` : 'Waiting…'}
          </button>
          <button class="btn ghost block" onClick={() => setStep(0)}>Back</button>
        </>
      )}
      {step === 2 && (
        <>
          <h1>Test each target</h1>
          <p>Shoot or tap every target once. Its tile lights up when the hit arrives.</p>
          <div class="card">
            <div class="tiles">{nodes.value.map((n) => <Tile key={n.mac} node={n} flash={isTested(n.slot)} />)}</div>
            <p class="num" style="margin-top:12px">{tested} of {nodes.value.length} tested</p>
          </div>
          <p class="muted" style="font-size:.85rem">A target that doesn't register can be tuned later in Targets → Hit sensor.</p>
          <button class="btn primary big block" onClick={() => finish(true)}>{tested === nodes.value.length ? 'Finish' : 'Finish anyway'}</button>
          <button class="btn ghost block" onClick={() => setStep(1)}>Back</button>
        </>
      )}
    </div>
  );
}
