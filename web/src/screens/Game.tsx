import { useEffect } from 'preact/hooks';
import { feed, game, modes, nodeAction, nodes, post, result } from '../api';
import { fmtMs, fmtTime, HoldButton, Tile } from '../components/ui';
import { keepAwake } from '../sound';

export function Hud() {
  const g = game.value;
  const h = g.hud || {};
  const name = modes.value.find((m) => m.id === g.mode)?.name || g.mode;
  useEffect(() => {
    keepAwake(true);
    return () => keepAwake(false);
  }, []);
  const timer = h.time_left !== undefined ? fmtTime(Number(h.time_left)) : h.level !== undefined ? `L${h.level}` : '';
  return (
    <div class="hud">
      <div class="top">
        <div style="flex:1">
          <b>{name}</b>
          <div class="muted" style="font-size:.85rem">{g.label}{g.player_name ? ` · ${g.player_name}` : ''}</div>
        </div>
        <HoldButton onDone={() => post('/api/v1/game/stop')}>Hold to stop</HoldButton>
      </div>
      <div class="big">
        <div class="statusline" style={h.status === 'FREEZE' || h.status === 'WRONG TARGET' ? 'color:var(--danger)' : ''}>
          {String(h.status ?? '')}
        </div>
        {timer && <div class="time">{timer}</div>}
        {h.score !== undefined && <div class="score">{String(h.score)}</div>}
        <div class="stats">
          {h.combo !== undefined && <span>combo <b>{String(h.combo)}</b></span>}
          {h.hits !== undefined && <span>hits <b>{String(h.hits)}</b></span>}
          {h.misses !== undefined && <span>misses <b>{String(h.misses)}</b></span>}
          {h.length !== undefined && Number(h.length) > 0 && <span>progress <b>{String(h.progress)}/{String(h.length)}</b></span>}
          {h.last_rt !== undefined && <span>last <b>{fmtMs(Number(h.last_rt))}</b></span>}
          {h.avg_rt !== undefined && <span>avg <b>{fmtMs(Number(h.avg_rt))}</b></span>}
        </div>
      </div>
      <div class="tiles">
        {nodes.value.map((n) => (
          <Tile key={n.mac} node={n} onClick={n.virtual ? () => nodeAction(n.mac, 'simhit') : undefined} />
        ))}
      </div>
      <div class="feed">
        {feed.value.map((f) => (
          <div key={f.id} class="feed-item">
            <span class={`pts ${f.pts > 0 ? 'pos' : f.pts < 0 ? 'neg' : ''}`}>{f.pts ? (f.pts > 0 ? `+${f.pts}` : f.pts) : '·'}</span>
            <span>{f.slot ? `#${f.slot}` : ''}</span>
            <span style="flex:1">{f.rt !== undefined ? fmtMs(f.rt) : ''}</span>
            <span class="muted">{f.note}</span>
          </div>
        ))}
      </div>
      {h.countdown ? <div class="countdown">{String(h.countdown)}</div> : null}
    </div>
  );
}

export function ResultView({ onAgain }: { onAgain: (mode: string) => void }) {
  const r = result.value!;
  const name = modes.value.find((m) => m.id === r.mode)?.name || r.mode;
  const s = r.stats;
  const slots = s.slots || [];
  const slowest = Math.max(1, ...slots.map((x) => x[2]));
  const stat = (label: string, v: unknown) => v !== undefined && (
    <div class="card"><div class="muted" style="font-size:.8rem">{label}</div><div class="num" style="font-size:1.3rem;font-weight:700">{String(v)}</div></div>
  );
  return (
    <div class="page stack">
      <div style="text-align:center">
        <h3>{name} · {r.label}</h3>
        <div class="num" style="font-size:4rem;font-weight:800;color:var(--accent);line-height:1">{r.score}</div>
        <p>
          {r.player_name || 'Guest'}
          {r.saved && r.rank ? ` · #${r.rank} on the leaderboard` : r.saved ? '' : ' · not saved'}
          {r.rank === 1 && ' 🏆'}
        </p>
      </div>
      <div class="grid2">
        {stat('Hits', s.hits)}
        {stat('Misses', s.misses ?? s.hostages_hit)}
        {s.avg_rt !== undefined && stat('Average reaction', fmtMs(Number(s.avg_rt)))}
        {s.best_rt !== undefined && stat('Best reaction', fmtMs(Number(s.best_rt)))}
        {stat('Best combo', s.max_combo)}
        {stat('Level', s.level)}
      </div>
      {slots.length > 1 && (
        <div class="card">
          <h3>Reaction time per target</h3>
          {slots.map(([slot, hits, rt]) => (
            <div key={slot} class="row" style="margin:8px 0">
              <span class="num" style="width:28px">#{slot}</span>
              <div style="flex:1"><div class="bar" style={`width:${(rt / slowest) * 100}%;${rt === slowest ? 'background:var(--warn)' : ''}`} /></div>
              <span class="num muted" style="width:120px;text-align:right">{fmtMs(rt)} · {hits}×</span>
            </div>
          ))}
          <p class="muted" style="font-size:.85rem">Orange = your slowest target.</p>
        </div>
      )}
      <button class="btn primary big block" onClick={() => onAgain(r.mode)}>Play again</button>
      <button class="btn block" onClick={() => (result.value = null)}>Done</button>
    </div>
  );
}
