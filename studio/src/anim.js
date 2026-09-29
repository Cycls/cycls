// Keyframes, app side: scene.py's evaluator in JS — the same arithmetic in the same order, so
// the app and the agent land on the same numbers — and the edits the timeline makes. Keys are
// Blender F-curves as the engine builds them: BEZIER, LINEAR or CONSTANT per key (for the
// segment to the next), AUTO_CLAMPED handles, no auto-smoothing, constant extrapolation.
// Both evaluators are held to samples Blender took (tests/fixtures/anim_golden.json).
import { clone } from "./doc.js";

export const CHANNELS = ["location", "rotation", "scale"];
const FLT_EPSILON = 1.1920929e-07;

// Key i's handles for component c, [[lx, ly], [rx, ry]] (scene.py _handle).
function handle(ks, i, c) {
  const x = ks[i][0], y = ks[i][1][c];
  const prev = i > 0 ? [ks[i - 1][0], ks[i - 1][1][c]] : null;
  const nxt = i + 1 < ks.length ? [ks[i + 1][0], ks[i + 1][1][c]] : null;
  if (!prev && !nxt) return [[x - 1, y], [x + 1, y]];
  const p1 = prev || [2 * x - nxt[0], 2 * y - nxt[1]];
  const p3 = nxt || [2 * x - p1[0], 2 * y - p1[1]];
  const dax = x - p1[0], day = y - p1[1], dbx = p3[0] - x, dby = p3[1] - y;
  let la = dax || 1, lb = dbx || 1;
  const tx = dbx / lb + dax / la, ty = dby / lb + day / la;
  const ln = tx * 2.5614;
  if (la > 5 * lb) la = 5 * lb;
  if (lb > 5 * la) lb = 5 * la;
  la = la / ln; lb = lb / ln;
  const lx = x - tx * la, rx = x + tx * lb;
  let ly = y - ty * la, ry = y + ty * lb;
  if (!prev || !nxt) return [[lx, y], [rx, y]];
  const yd1 = prev[1] - y, yd2 = nxt[1] - y;
  if ((yd1 <= 0 && yd2 <= 0) || (yd1 >= 0 && yd2 >= 0)) return [[lx, y], [rx, y]];
  const left = (yd1 <= 0 && prev[1] > ly) || (yd1 > 0 && prev[1] < ly);
  const right = (yd1 <= 0 && nxt[1] < ry) || (yd1 > 0 && nxt[1] > ry);
  if (left) ly = prev[1];
  if (right) ry = nxt[1];
  if (left) ry = y + (y - ly) / (lx - x) * (x - rx);
  else if (right) ly = y + (y - ry) / (x - rx) * (lx - x);
  return [[lx, ly], [rx, ry]];
}

function bezier(v1, v2, v3, v4, frame) {
  const span = v4[0] - v1[0];
  const h1x = v1[0] - v2[0], h1y = v1[1] - v2[1], h2x = v4[0] - v3[0], h2y = v4[1] - v3[1];
  if (Math.abs(h1x) + Math.abs(h2x) !== 0) {
    if (Math.abs(h1x) > span) { const f = span / Math.abs(h1x); v2 = [v1[0] - f * h1x, v1[1] - f * h1y]; }
    if (Math.abs(h2x) > span) { const f = span / Math.abs(h2x); v3 = [v4[0] - f * h2x, v4[1] - f * h2y]; }
  }
  const at = (p0, p1, p2, p3, t) => {
    const u = 1 - t;
    return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3;
  };
  let lo = 0, hi = 1;
  for (let n = 0; n < 64; n++) {
    const mid = (lo + hi) / 2;
    if (at(v1[0], v2[0], v3[0], v4[0], mid) < frame) lo = mid; else hi = mid;
  }
  return at(v1[1], v2[1], v3[1], v4[1], (lo + hi) / 2);
}

// A channel's value at `frame` (fractions are fine).
export function sample(ks, frame) {
  if (frame <= ks[0][0]) return [...ks[0][1]];
  if (frame >= ks[ks.length - 1][0]) return [...ks[ks.length - 1][1]];
  let i = 0;
  while (ks[i + 1][0] <= frame) i++;
  const k0 = ks[i], k1 = ks[i + 1];
  if (k0[0] === frame) return [...k0[1]];
  const out = [];
  for (let c = 0; c < 3; c++) {
    const y0 = k0[1][c], y1 = k1[1][c];
    if (k0[2] === "constant") out.push(y0);
    else if (k0[2] === "linear") out.push(y0 + (frame - k0[0]) / (k1[0] - k0[0]) * (y1 - y0));
    else {
      const r = handle(ks, i, c)[1], l = handle(ks, i + 1, c)[0];
      if (Math.abs(y0 - y1) < FLT_EPSILON && Math.abs(r[1] - l[1]) < FLT_EPSILON && Math.abs(l[1] - y1) < FLT_EPSILON) out.push(y0);
      else out.push(bezier([k0[0], y0], r, l, [k1[0], y1], frame));
    }
  }
  return out;
}

export const channelAt = (o, ch, frame) => (o.keys?.[ch] ? sample(o.keys[ch], frame) : [...o[ch]]);
export const pose = (o, frame) => ({ location: channelAt(o, "location", frame), rotation: channelAt(o, "rotation", frame),
                                     scale: channelAt(o, "scale", frame) });
export const animated = (doc) => Object.keys(doc.objects).filter((id) => doc.objects[id].keys);

// The document as it stands at `frame`: what the viewport draws. Untouched when still.
export function posed(doc, frame) {
  const ids = animated(doc);
  if (!ids.length || frame == null) return doc;
  const objects = { ...doc.objects };
  for (const id of ids) objects[id] = { ...objects[id], ...pose(objects[id], frame) };
  return { ...doc, objects };
}

// Every frame the object has a key on, any channel.
export function keyFrames(o) {
  const set = new Set();
  for (const ks of Object.values(o?.keys || {})) for (const k of ks) set.add(k[0]);
  return [...set].sort((a, b) => a - b);
}

// An animated channel rests where its keys put the first frame (scene.py normalize).
export function pinStill(doc) {
  const f = doc.animation.frame_start;
  for (const o of Object.values(doc.objects)) for (const [ch, ks] of Object.entries(o.keys || {})) o[ch] = sample(ks, f);
  return doc;
}

// Key `chans` of object `o` (mutated) at `frame` with `values` (by channel), or where it is then.
export function setKeys(o, frame, chans = CHANNELS, values = {}, interp = "bezier") {
  const keys = o.keys || {};
  for (const ch of chans) {
    const v = values[ch] ? [...values[ch]] : channelAt(o, ch, frame);
    keys[ch] = [...(keys[ch] || []).filter((k) => k[0] !== frame), [frame, v, interp]].sort((a, b) => a[0] - b[0]);
  }
  o.keys = keys;
}

// Remove keys at `frame` (or all of them when null) on `chans`.
export function removeKeys(o, frame = null, chans = CHANNELS) {
  if (!o.keys) return;
  for (const ch of chans) {
    if (!o.keys[ch]) continue;
    o.keys[ch] = frame == null ? [] : o.keys[ch].filter((k) => k[0] !== frame);
    if (!o.keys[ch].length) delete o.keys[ch];
  }
  if (!Object.keys(o.keys).length) delete o.keys;
}

// The interpolation of keys at `frame` (the segments they start).
export function setInterpolation(o, frame, interp) {
  for (const ks of Object.values(o.keys || {})) for (const k of ks) if (k[0] === frame) k[2] = interp;
}

// scene.py _op_turntable: the objects spin on the spot under a new empty at their base
// centre, 0° at the first frame to turns × 360° one frame past the last — a seamless loop.
export function turntable(doc, ids, base, { turns = 1, id = "turntable" } = {}) {
  const d = clone(doc);
  const a = d.animation;
  d.objects[id] = { name: "Turntable", type: "empty", parent: null, location: [...base], rotation: [0, 0, 0],
                    scale: [1, 1, 1], visible: true, renderable: true,
                    keys: { rotation: [[a.frame_start, [0, 0, 0], "linear"], [a.frame_end + 1, [0, 0, 360 * turns], "linear"]] } };
  for (const oid of ids) {
    const o = d.objects[oid];
    const shift = (v) => v.map((x, i) => x - base[i]);
    o.location = shift(o.location);
    for (const k of o.keys?.location || []) k[1] = shift(k[1]);
    o.parent = id;
  }
  return pinStill(d);
}
