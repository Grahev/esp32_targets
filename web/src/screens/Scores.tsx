import { useEffect, useState } from 'preact/hooks';
import { loadModes, loadPlayers, modes, players, post, type Player } from '../api';
import { fmtMs, Sheet } from '../components/ui';

interface Entry { s: number; p: number; n: string; d: number; l: string; avg_rt?: number; hits?: number; level?: number; m?: string;
  slots?: [number, number, number][] }

function date(epoch: number) {
  if (!epoch) return '';
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

async function history(): Promise<Entry[]> {
  try {
    const t = await (await fetch('/api/v1/history')).text();
    return t.split('\n').filter(Boolean).map((l) => {
      try {
        return JSON.parse(l) as Entry;
      } catch {
        return null;
      }
    }).filter((x): x is Entry => !!x);
  } catch {
    return [];
  }
}

function Profile({ player, onClose }: { player: Player; onClose: () => void }) {
  const [games, setGames] = useState<Entry[] | null>(null);
  const [name, setName] = useState(player.name);
  useEffect(() => {
    history().then((h) => setGames(h.filter((e) => e.p === player.id).reverse()));
  }, []);
  // Average reaction per target over all saved games
  const perSlot = new Map<number, { hits: number; rt: number }>();
  for (const g of games || []) for (const [slot, hits, rt] of g.slots || []) {
    const v = perSlot.get(slot) || { hits: 0, rt: 0 };
    perSlot.set(slot, { hits: v.hits + hits, rt: v.rt + rt * hits });
  }
  const slots = [...perSlot.entries()].map(([s, v]) => [s, Math.round(v.rt / v.hits)] as const).sort((a, b) => a[0] - b[0]);
  const slowest = slots.length > 1 ? slots.reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
  const rename = async () => {
    if ((await post(`/api/v1/players?action=update&id=${player.id}`, { name })).ok) loadPlayers();
  };
  const del = async () => {
    if (confirm(`Delete ${player.name}? Their scores stay on the leaderboard.`)) {
      if ((await post(`/api/v1/players?action=delete&id=${player.id}`)).ok) {
        loadPlayers();
        onClose();
      }
    }
  };
  return (
    <Sheet onClose={onClose}>
      <h1>{player.name}</h1>
      <p class="muted">{player.games} saved game{player.games === 1 ? '' : 's'}</p>
      {slowest && (
        <div class="card" style="margin:12px 0">
          <b>Slowest target: #{slowest[0]}</b>
          <p class="muted">Average {fmtMs(slowest[1])}. Practise that side.</p>
          {slots.map(([s, rt]) => <div key={s} class="row spread num"><span>#{s}</span><span>{fmtMs(rt)}</span></div>)}
        </div>
      )}
      <h3>Recent games</h3>
      {games === null && <p class="muted">Loading…</p>}
      {games?.length === 0 && <p class="muted">No saved games yet.</p>}
      <table>
        <tbody>
          {games?.slice(0, 15).map((g, i) => (
            <tr key={i}>
              <td>{modes.value.find((m) => m.id === g.m)?.name || g.m}<div class="muted" style="font-size:.8rem">{g.l} {date(g.d)}</div></td>
              <td class="r num"><b>{g.s}</b></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div class="section row">
        <input type="text" value={name} maxLength={20} onInput={(e) => setName((e.target as HTMLInputElement).value)} />
        <button class="btn" onClick={rename} disabled={!name.trim() || name === player.name}>Rename</button>
      </div>
      <button class="btn danger block" style="margin-top:12px" onClick={del}>Delete player</button>
    </Sheet>
  );
}

export function Scores() {
  const saved = modes.value.filter((m) => m.id !== 'free_practice');
  const [mode, setMode] = useState(saved[0]?.id || 'time_attack');
  const [label, setLabel] = useState('All');
  const [rows, setRows] = useState<Entry[] | null>(null);
  const [profile, setProfile] = useState<Player | null>(null);
  useEffect(() => {
    if (!modes.value.length) loadModes();
    loadPlayers();
  }, []);
  useEffect(() => {
    setRows(null);
    setLabel('All');
    fetch(`/api/v1/scores?mode=${mode}`).then((r) => r.json()).then(setRows).catch(() => setRows([]));
  }, [mode]);
  const labels = ['All', ...new Set((rows || []).map((r) => r.l))];
  const shown = (rows || []).filter((r) => label === 'All' || r.l === label);
  const isBreach = mode === 'breach';
  return (
    <div class="page stack">
      <h1>Scores</h1>
      <div class="chips">
        {saved.map((m) => <button key={m.id} class={`chip ${m.id === mode ? 'on' : ''}`} onClick={() => setMode(m.id)}>{m.name}</button>)}
      </div>
      {labels.length > 2 && (
        <div class="chips">
          {labels.map((l) => <button key={l} class={`chip ${l === label ? 'on' : ''}`} onClick={() => setLabel(l)}>{l}</button>)}
        </div>
      )}
      <div class="card">
        {rows === null && <p class="muted">Loading…</p>}
        {rows && !shown.length && <div class="empty">No scores yet. Go and play!</div>}
        {shown.length > 0 && (
          <table>
            <thead><tr><th>#</th><th>Player</th><th class="r">{isBreach ? 'Level' : 'Avg'}</th><th class="r">Score</th></tr></thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i}>
                  <td class="num">{i + 1}</td>
                  <td>{r.n}<div class="muted" style="font-size:.8rem">{label === 'All' ? r.l : ''} {date(r.d)}</div></td>
                  <td class="r num muted">{isBreach ? r.level : r.avg_rt ? fmtMs(r.avg_rt) : ''}</td>
                  <td class="r num"><b>{r.s}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <section>
        <h3>Players</h3>
        {!players.value.length && <p class="muted">Add players on the Play screen.</p>}
        <div class="chips" style="flex-wrap:wrap">
          {players.value.map((p) => <button key={p.id} class="chip" onClick={() => setProfile(p)}>{p.name} <span class="muted">· {p.games}</span></button>)}
        </div>
      </section>
      {profile && <Profile player={profile} onClose={() => setProfile(null)} />}
    </div>
  );
}
