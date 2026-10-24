import { useEffect, useState } from 'preact/hooks';
import { game, nodeAction, nodes, pending, post, sensorHits, settings, sysMode, taps, type Node } from '../api';
import { Battery, Field, Sheet, Stepper, Tile, Toggle } from '../components/ui';

function signal(rssi: number) {
  if (!rssi) return '–';
  return rssi > -60 ? 'strong' : rssi > -75 ? 'ok' : 'weak';
}

function NodeSheet({ node, onClose }: { node: Node; onClose: () => void }) {
  const [name, setName] = useState(node.name);
  const [slot, setSlot] = useState(node.slot);
  const [cfg, setCfg] = useState({ ...node.cfg });
  const [volts, setVolts] = useState('');
  const max = settings.value?.max_nodes ?? 5;

  const save = async () => {
    const body: Record<string, unknown> = { name, cfg: {
      debounce_ms: cfg.debounce_ms, glitch_edges: cfg.glitch_edges, glitch_window_ms: cfg.glitch_window_ms,
      hit_flash: cfg.hit_flash, led_pin: cfg.led_pin } };
    if (slot !== node.slot) body.slot = slot;
    if ((await nodeAction(node.mac, 'update', body)).ok) onClose();
  };
  const calibrate = async () => {
    const v = parseFloat(volts.replace(',', '.'));
    if (!(v > 2.5 && v < 4.6)) return;
    if ((await nodeAction(node.mac, 'calibrate', { mv: Math.round(v * 1000) })).ok) setVolts('');
  };
  const forget = async () => {
    if (confirm(`Remove ${node.name}? It will show up as a new target next time it starts.`)) {
      if ((await nodeAction(node.mac, 'forget')).ok) onClose();
    }
  };

  return (
    <Sheet onClose={onClose}>
      <div class="row spread">
        <h1>Target {node.slot}</h1>
        <button class="btn" onClick={() => nodeAction(node.mac, 'identify')} disabled={!node.online}>Blink</button>
      </div>
      <p class="muted num" style="font-size:.85rem">{node.mac} · fw {node.fw}{node.virtual ? ' · simulated' : ''}</p>
      <div class="card">
        <Field label="Name"><input type="text" maxLength={20} value={name} style="max-width:200px"
          onInput={(e) => setName((e.target as HTMLInputElement).value)} /></Field>
        <Field label="Number" hint="Swaps with the target that has it">
          <Stepper value={slot} min={1} max={max} onChange={setSlot} />
        </Field>
      </div>
      <div class="section">
        <h3>Hit sensor</h3>
        <div class="card">
          <Field label="Lockout after a hit" hint="Longer = fewer double hits">
            <Stepper value={cfg.debounce_ms} min={50} max={2000} step={50} unit="ms" onChange={(v) => setCfg({ ...cfg, debounce_ms: v })} />
          </Field>
          <Field label="Pulses needed" hint="More = ignores light knocks and wind">
            <Stepper value={cfg.glitch_edges} min={1} max={10} onChange={(v) => setCfg({ ...cfg, glitch_edges: v })} />
          </Field>
          <Field label="Within">
            <Stepper value={cfg.glitch_window_ms} min={5} max={200} step={5} unit="ms" onChange={(v) => setCfg({ ...cfg, glitch_window_ms: v })} />
          </Field>
          <Field label="Flash white on a hit">
            <Toggle value={cfg.hit_flash} onChange={(v) => setCfg({ ...cfg, hit_flash: v })} />
          </Field>
        </div>
      </div>
      <button class="btn primary block big" style="margin-top:12px" onClick={save}>Save</button>
      {!node.virtual && (
        <div class="section">
          <h3>Battery</h3>
          <div class="card stack">
            <p>Reads <b class="num">{(node.batt_mv / 1000).toFixed(2)} V</b> · <Battery node={node} /></p>
            <p class="muted" style="font-size:.9rem">Measure the battery with a multimeter and enter the reading to calibrate.</p>
            <div class="row">
              <input type="number" inputMode="decimal" step="0.01" placeholder="e.g. 3.92" value={volts}
                onInput={(e) => setVolts((e.target as HTMLInputElement).value)} />
              <button class="btn" onClick={calibrate} disabled={!volts}>Calibrate</button>
            </div>
          </div>
        </div>
      )}
      <div class="section row">
        {!node.virtual && <button class="btn" onClick={() => nodeAction(node.mac, 'reboot')} disabled={!node.online}>Restart</button>}
        {!node.virtual && <button class="btn danger" onClick={forget}>Remove</button>}
      </div>
    </Sheet>
  );
}

function SensorTest() {
  const on = sysMode.value === 'sensor_test';
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 500);
    return () => clearInterval(t);
  }, []);
  return (
    <div class="card stack">
      <div class="row spread">
        <div>
          <b>Sensor test</b>
          <div class="muted" style="font-size:.85rem">Targets flash green on every hit. Shoot each one a few times.</div>
        </div>
        <Toggle value={on} label="Sensor test" onChange={(v) => post('/api/v1/sensor_test', { on: v })} />
      </div>
      {on && (
        <table>
          <thead><tr><th>Target</th><th class="r">Hits</th><th class="r">Pulses</th></tr></thead>
          <tbody>
            {nodes.value.map((n) => {
              const s = sensorHits.value[n.slot];
              const fresh = s && Date.now() - s.at < 700;
              return (
                <tr key={n.mac} style={fresh ? 'background:var(--surface-2)' : ''}>
                  <td>#{n.slot} {n.name}</td>
                  <td class="r num">{s?.hits ?? '–'}</td>
                  <td class="r num">{s?.edges ?? '–'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function Targets() {
  const [open, setOpen] = useState<string | null>(null);
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 600);  // clears tap highlights
    return () => clearInterval(t);
  }, []);
  const node = nodes.value.find((n) => n.mac === open);
  const max = settings.value?.max_nodes ?? 5;
  return (
    <div class="page stack">
      <div class="row spread">
        <h1>Targets <span class="muted num">{nodes.value.length}/{max}</span></h1>
      </div>
      <p class="muted" style="font-size:.9rem">Hit a target to see which card it is. Switch on a new target and it appears here.</p>

      {pending.value.map((p) => (
        <div key={p.mac} class="card row spread" style="border-color:var(--warn)">
          <div>
            <b>New target found</b>
            <div class="muted num" style="font-size:.85rem">{p.mac} · fw {p.fw}</div>
          </div>
          <div class="row">
            <button class="btn ghost" onClick={() => nodeAction(p.mac, 'forget')}>Ignore</button>
            <button class="btn primary" onClick={() => nodeAction(p.mac, 'accept')}>Add</button>
          </div>
        </div>
      ))}

      {!nodes.value.length && !pending.value.length && (
        <div class="empty card">
          <p><b>No targets yet</b></p>
          <p>Switch a target on. Its light breathes white while it looks for the hub, then turns dim blue when it's connected.</p>
        </div>
      )}

      {nodes.value.map((n) => {
        const tapped = taps.value[n.slot] && Date.now() - taps.value[n.slot] < 700;
        return (
          <button key={n.mac} class="card node-card" style="width:100%;text-align:left" onClick={() => setOpen(n.mac)}>
            <Tile node={n} flash={!!tapped} />
            <div class="info">
              <div class="name">{n.name}</div>
              <div class="muted" style="font-size:.85rem">
                {n.online ? <>● online · <Battery node={n} /> · signal {signal(n.rssi)}</> : '○ offline'}
              </div>
            </div>
            <span class="muted">›</span>
          </button>
        );
      })}

      {nodes.value.length > 0 && !game.value.running && <SensorTest />}
      {node && <NodeSheet node={node} onClose={() => setOpen(null)} />}
    </div>
  );
}
