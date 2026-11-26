// The short sound something new makes while the app is open. A page may play sound only after the person has clicked
// or typed in it once, so the first of those opens it; until then only the count shows. Kept on the device.
const KEY = "cycls_sounds";
let ctx: AudioContext | null = null;

export function soundsOn() {
  try { return localStorage.getItem(KEY) !== "off"; } catch { return true; }
}

export function setSoundsOn(on: boolean) {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* private mode */ }
}

if (typeof window !== "undefined") {
  const wake = () => {
    try { ctx ??= new AudioContext(); void ctx.resume(); } catch { /* no audio here */ }
  };
  window.addEventListener("pointerdown", wake, { once: true });
  window.addEventListener("keydown", wake, { once: true });
}

export function chime() {
  if (!ctx || ctx.state !== "running" || !soundsOn()) return;
  const at = ctx.currentTime;
  for (const [hz, start] of [[880, 0], [1320, 0.09]]) {
    const tone = ctx.createOscillator(), gain = ctx.createGain();
    tone.frequency.value = hz;
    gain.gain.setValueAtTime(0.0001, at + start);
    gain.gain.exponentialRampToValueAtTime(0.12, at + start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + start + 0.35);
    tone.connect(gain).connect(ctx.destination);
    tone.start(at + start);
    tone.stop(at + start + 0.4);
  }
}
