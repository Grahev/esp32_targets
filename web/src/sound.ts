// Beeps (Web Audio, works on plain http after the first tap) and vibration.
let ctx: AudioContext | null = null;

export function unlockAudio() {
  if (!ctx) {
    const C = window.AudioContext || (window as any).webkitAudioContext;
    if (C) ctx = new C();
  }
  ctx?.resume();
}

export function beep(freq: number, seconds: number, type: OscillatorType = 'square') {
  if (!ctx || ctx.state !== 'running') return;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = type;
  o.frequency.value = freq;
  g.gain.setValueAtTime(0.12, ctx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + seconds);
  o.connect(g).connect(ctx.destination);
  o.start();
  o.stop(ctx.currentTime + seconds);
}

export function buzz(pattern: number | number[]) {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* not supported (iOS) */
  }
}

// Keep the screen on during a game. The Wake Lock API needs HTTPS, which the
// hub can't offer, so fall back to a playing (silent, invisible) video.
let lock: any = null;
let video: HTMLVideoElement | null = null;

export async function keepAwake(on: boolean) {
  if (on) {
    try {
      lock = await (navigator as any).wakeLock?.request('screen');
      if (lock) return;
    } catch {
      /* not allowed here */
    }
    try {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 2;
      const stream = (canvas as any).captureStream?.(1);
      if (!stream) return;
      video = document.createElement('video');
      video.muted = true;
      video.setAttribute('playsinline', '');
      video.srcObject = stream;
      video.style.cssText = 'position:fixed;width:1px;height:1px;opacity:0;pointer-events:none';
      document.body.appendChild(video);
      await video.play();
    } catch {
      /* best effort */
    }
  } else {
    lock?.release?.();
    lock = null;
    video?.remove();
    video = null;
  }
}
