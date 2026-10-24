import { useState } from 'preact/hooks';
import { connected, everConnected, game, lowestBattery, nodes, online, post, result, settings } from './api';
import { Icon, Toasts } from './components/ui';
import { Hud, ResultView } from './screens/Game';
import { Play } from './screens/Play';
import { Scores } from './screens/Scores';
import { Settings } from './screens/Settings';
import { Targets } from './screens/Targets';
import { Wizard } from './screens/Wizard';
import { unlockAudio } from './sound';

type Tab = 'play' | 'targets' | 'scores' | 'settings';
const TABS: [Tab, string][] = [['play', 'Play'], ['targets', 'Targets'], ['scores', 'Scores'], ['settings', 'Settings']];

function StatusBar() {
  const s = settings.value;
  const max = s?.max_nodes ?? 5;
  const low = lowestBattery.value;
  return (
    <header class="status">
      <span class="title">{s?.name ?? 'Targets'}</span>
      <span class="dots" aria-label={`${online.value.length} targets online`}>
        {Array.from({ length: Math.max(max, nodes.value.length) }, (_, i) => (
          <span key={i} class={`dot ${i < online.value.length ? 'on' : ''}`} />
        ))}
      </span>
      {low !== undefined && <span class={`batt ${low < 20 ? 'low' : ''}`}>🔋{low}%</span>}
      <span class={`conn ${connected.value ? '' : 'bad'}`}>{connected.value ? 'live' : 'offline'}</span>
    </header>
  );
}

function again(mode: string) {
  let cfg = {};
  let player = 0;
  try {
    cfg = JSON.parse(localStorage.getItem('targets.cfg.' + mode) || '{}');
    player = JSON.parse(localStorage.getItem('targets.player') || '0');
  } catch {
    /* defaults */
  }
  result.value = null;
  post('/api/v1/game/start', { mode, settings: cfg, player, force: true });
}

export function App() {
  const [tab, setTab] = useState<Tab>('play');
  const [wizard, setWizard] = useState(false);
  if (!everConnected.value) {
    return (
      <div class="page empty">
        <h1>Connecting to the hub…</h1>
        <p>Make sure this phone is on the hub's WiFi. If your phone asks, choose <b>Stay connected</b> (the hub has no internet).</p>
      </div>
    );
  }
  if (game.value.running) return <><Hud /><Toasts /></>;
  const showWizard = wizard || (settings.value && !settings.value.wizard_done);
  return (
    <div onPointerDown={unlockAudio} style="display:contents">
      {!connected.value && <div class="banner">Reconnecting to the hub…</div>}
      <StatusBar />
      {showWizard ? (
        <Wizard onDone={() => setWizard(false)} />
      ) : result.value ? (
        <ResultView onAgain={again} />
      ) : (
        <>
          {tab === 'play' && <Play />}
          {tab === 'targets' && <Targets />}
          {tab === 'scores' && <Scores />}
          {tab === 'settings' && <Settings onWizard={() => setWizard(true)} />}
          <nav class="tabs">
            {TABS.map(([id, label]) => (
              <button key={id} class={tab === id ? 'active' : ''} onClick={() => setTab(id)} aria-current={tab === id}>
                <Icon name={id} />
                {label}
              </button>
            ))}
          </nav>
        </>
      )}
      <Toasts />
    </div>
  );
}
