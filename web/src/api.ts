// Connection to the hub: one WebSocket for live state (with reconnect), REST
// for actions. All app state lives in these signals.
import { signal, computed } from '@preact/signals';
import { beep, buzz } from './sound';

export interface Led { e: number; c: string }
export interface Node {
  mac: string; slot: number; name: string; color: number; virtual: boolean; online: boolean;
  batt_mv: number; batt_pct?: number; rssi: number; fw: string; uptime_s: number; hits: number;
  cfg: { debounce_ms: number; glitch_edges: number; glitch_window_ms: number; batt_scale_uv: number; hit_flash: boolean; led_pin: number };
  led: Led;
}
export interface Pending { mac: string; fw: string; batt_pct?: number; age_s: number }
export interface Settings {
  name: string; has_password: boolean; channel: number; brightness: number; auto_accept: boolean;
  max_nodes: number; hb_interval_s: number; sounds: boolean; difficulty: string;
  virtual_nodes: number; virtual_autoshoot: boolean; wizard_done: boolean;
}
export type Hud = Record<string, number | string | boolean>;
export interface Game { running: boolean; mode?: string; label?: string; player?: number; player_name?: string; hud?: Hud }
export interface Result {
  mode: string; label: string; score: number; player?: number; player_name?: string;
  saved: boolean; rank: number; stats: Record<string, unknown> & { slots?: [number, number, number][] };
}
export interface Ota { active: boolean; total: number; slot?: number; phase?: string; pct?: number; done: string[]; failed: string[] }
export interface FeedItem { id: number; slot: number; pts: number; rt?: number; note?: string }
export interface Toast { id: number; level: 'info' | 'warn' | 'error'; msg: string }
export interface Setting {
  key: string; label: string; type: 'int' | 'enum' | 'bool'; min?: number; max?: number;
  def: number | string | boolean; unit?: string; options?: string[];
}
export interface ModeSchema {
  id: string; name: string; min_nodes: number; tagline: string; rules: string[];
  settings: Setting[]; presets: Record<string, Record<string, unknown>>;
}
export interface Player { id: number; name: string; color: number; games: number }

export const connected = signal(false);
export const everConnected = signal(false);
export const fw = signal('');
export const settings = signal<Settings | null>(null);
export const nodes = signal<Node[]>([]);
export const pending = signal<Pending[]>([]);
export const game = signal<Game>({ running: false });
export const result = signal<Result | null>(null);
export const sysMode = signal('idle');
export const safeMode = signal(false);
export const ota = signal<Ota | null>(null);
export const feed = signal<FeedItem[]>([]);
export const toasts = signal<Toast[]>([]);
export const taps = signal<Record<number, number>>({});     // slot -> time of last hit outside a game
export const sensorHits = signal<Record<number, { hits: number; edges: number; at: number }>>({});
export const modes = signal<ModeSchema[]>([]);
export const players = signal<Player[]>([]);

export const online = computed(() => nodes.value.filter((n) => n.online));
export const lowestBattery = computed(() => {
  const v = online.value.filter((n) => !n.virtual && n.batt_pct !== undefined).map((n) => n.batt_pct as number);
  return v.length ? Math.min(...v) : undefined;
});

let seq = 1;

export function toast(msg: string, level: Toast['level'] = 'info') {
  const t = { id: seq++, level, msg };
  toasts.value = [...toasts.value.slice(-2), t];
  setTimeout(() => (toasts.value = toasts.value.filter((x) => x.id !== t.id)), level === 'error' ? 6000 : 3500);
}

function soundsOn() {
  return settings.value?.sounds !== false;
}

function handle(m: any) {
  switch (m.t) {
    case 'state':
      fw.value = m.fw;
      settings.value = m.settings;
      nodes.value = m.nodes;
      pending.value = m.pending;
      game.value = m.game;
      sysMode.value = m.mode;
      safeMode.value = m.safe_mode;
      ota.value = m.ota?.active || m.ota?.done?.length || m.ota?.failed?.length ? m.ota : null;
      break;
    case 'nodes':
      nodes.value = m.nodes;
      pending.value = m.pending;
      break;
    case 'leds': {
      const map = new Map<number, Led>(m.v.map((x: [number, number, string]) => [x[0], { e: x[1], c: x[2] }]));
      nodes.value = nodes.value.map((n) => (map.has(n.slot) ? { ...n, led: map.get(n.slot)! } : n));
      break;
    }
    case 'game': {
      const was = game.value.running;
      game.value = m.game;
      if (m.game.running && !was) {
        feed.value = [];
        result.value = null;
      }
      break;
    }
    case 'hud': {
      const before = game.value.hud;
      game.value = { ...game.value, hud: m.hud };
      if (soundsOn() && before && m.hud.countdown !== before.countdown && m.hud.countdown) beep(660, 0.08);
      if (soundsOn() && before?.status !== 'GO' && m.hud.status === 'GO') beep(990, 0.25);
      break;
    }
    case 'feed': {
      feed.value = [{ id: seq++, slot: m.slot, pts: m.pts, rt: m.rt, note: m.note }, ...feed.value].slice(0, 30);
      if (soundsOn()) m.pts < 0 ? beep(180, 0.25, 'sawtooth') : beep(m.pts >= 10 ? 1200 : 880, 0.06);
      buzz(m.pts < 0 ? [80, 60, 80] : 25);
      break;
    }
    case 'result':
      result.value = m.result;
      if (soundsOn()) beep(520, 0.4);
      break;
    case 'settings':
      settings.value = m.settings;
      break;
    case 'toast':
      toast(m.msg, m.level);
      break;
    case 'ota':
      ota.value = m.ota;
      break;
    case 'tap':
      taps.value = { ...taps.value, [m.slot]: Date.now() };
      break;
    case 'sensor':
      sensorHits.value = { ...sensorHits.value, [m.slot]: { hits: m.hits, edges: m.edges, at: Date.now() } };
      if (soundsOn()) beep(1000, 0.05);
      break;
  }
}

let ws: WebSocket | null = null;
let backoff = 500;

export function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    connected.value = true;
    everConnected.value = true;
    backoff = 500;
    ws?.send(JSON.stringify({ t: 'hello', time: Date.now() }));  // the hub has no clock
  };
  ws.onmessage = (e) => {
    try {
      handle(JSON.parse(e.data));
    } catch {
      /* ignore a bad frame */
    }
  };
  ws.onclose = () => {
    connected.value = false;
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };
}

export interface Reply { ok: boolean; msg?: string; confirm?: string; [k: string]: unknown }

export async function post(path: string, body: unknown = {}, quiet = false): Promise<Reply> {
  try {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const j = (await r.json().catch(() => ({ ok: r.ok }))) as Reply;
    if (!r.ok && !j.confirm && !quiet) toast(j.msg || `Error ${r.status}`, 'error');
    return { ...j, ok: r.ok };
  } catch {
    if (!quiet) toast('Hub not reachable. Are you on its WiFi?', 'error');
    return { ok: false };
  }
}

export async function get<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(path);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function loadModes() {
  const m = await get<ModeSchema[]>('/api/v1/modes');
  if (m) modes.value = m;
}

export async function loadPlayers() {
  const p = await get<Player[]>('/api/v1/players');
  if (p) players.value = p;
}

export const nodeAction = (mac: string, action: string, body: unknown = {}) =>
  post(`/api/v1/node?mac=${mac}&action=${action}`, body);
