// How long a Cycles render will take, from this workspace's own renders (data/renders.json
// logs resolution, samples and Blender's seconds): seconds ≈ a + b · (pixels × samples / 1e6),
// least squares over the recent ones, or a prior until there are some. Plus the round trip.

const PRIOR = { a: 1, b: 0.8 };        // 1280×720 at 32 samples ≈ 24 s on the 8-core engine
const TRIP = 4;                        // upload, scene build, preview, answer

export function workOf(width, height, samples) {
  return (width * height * samples) / 1e6;
}

export function fit(history) {
  const pts = (Array.isArray(history) ? history : [])
    .filter((r) => r && Array.isArray(r.resolution) && r.samples > 0 && r.seconds > 0)
    .slice(-12)
    .map((r) => [workOf(r.resolution[0], r.resolution[1], r.samples), r.seconds]);
  if (!pts.length) return PRIOR;
  const n = pts.length, mx = pts.reduce((s, p) => s + p[0], 0) / n, my = pts.reduce((s, p) => s + p[1], 0) / n;
  const sxx = pts.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
  if (n >= 3 && sxx > 1e-6) {
    const b = pts.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0) / sxx;
    const a = my - b * mx;
    if (b > 0 && a >= -5) return { a: Math.max(0, a), b };
  }
  const rates = pts.map(([w, t]) => t / Math.max(w, 1e-6)).sort((x, y) => x - y);
  return { a: 0, b: rates[Math.floor(rates.length / 2)] };
}

export function estimateSeconds(history, width, height, samples) {
  const { a, b } = fit(history);
  return Math.round(a + b * workOf(width, height, samples) + TRIP);
}
