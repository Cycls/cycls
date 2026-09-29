// What the app can say about itself from inside its sandbox. Errors always go to
// data/errors.json (the host's console can't see this frame); a diagnostic build
// (VITE_STUDIO_DIAG=1) also writes counters to data/diag.json every few seconds.
export const diag = { started: new Date().toISOString(), frames: 0, syncs: 0, resizes: 0, host: null, canvas: null,
                      errors: [], status: null, objects: 0, evaluations: 0 };
const DIAG = import.meta.env.VITE_STUDIO_DIAG === "1";

function write(name, value) {
  try { window.cycls?.write(`data/${name}`, JSON.stringify(value, null, 1)); } catch { /* nowhere to report */ }
}

export function recordError(where, err) {
  const text = `${where}: ${err && (err.stack || err.message) || err}`.slice(0, 1500);
  diag.errors = [...diag.errors.slice(-19), { at: new Date().toISOString(), text }];
  write("errors.json", diag.errors);
}

addEventListener("error", (e) => recordError("error", e.error || e.message));
addEventListener("unhandledrejection", (e) => recordError("promise", e.reason));

if (DIAG) setInterval(() => write("diag.json", diag), 3000);
