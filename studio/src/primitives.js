// Primitive geometry for the viewport, in Blender's space (Z up) and at Blender's
// sizes, so what the user drags is where Blender renders it. Topology is close
// (not vertex-identical) — Blender's own mesh arrives via `evaluate` whenever a
// modifier or an exact shape (text, monkey) matters.
import * as THREE from "three";

const zUp = (g) => g.rotateX(Math.PI / 2);   // three's Y-up solids → Blender's Z-up

export function primitiveGeometry(m) {
  switch (m.primitive) {
    case "plane": return new THREE.PlaneGeometry(m.size, m.size);
    case "grid": return new THREE.PlaneGeometry(m.size, m.size, m.x_segments, m.y_segments);
    case "circle":
      return m.fill === "none" ? ringOutline(m.radius, m.vertices) : new THREE.CircleGeometry(m.radius, m.vertices);
    case "cube": return new THREE.BoxGeometry(m.size, m.size, m.size);
    case "uv_sphere": return zUp(new THREE.SphereGeometry(m.radius, m.segments, m.ring_count));
    case "ico_sphere": return new THREE.IcosahedronGeometry(m.radius, Math.max(0, m.subdivisions - 1));
    case "cylinder": return zUp(new THREE.CylinderGeometry(m.radius, m.radius, m.depth, m.vertices));
    case "cone": return zUp(new THREE.CylinderGeometry(m.radius2, m.radius1, m.depth, m.vertices));
    case "torus": return new THREE.TorusGeometry(m.major_radius, m.minor_radius, m.minor_segments, m.major_segments);
    case "cyclorama": return cyclorama(m);
    case "monkey": return monkeyStandIn(m.size);
    default: return new THREE.BoxGeometry(1, 1, 1);
  }
}

function ringOutline(r, n) {
  const g = new THREE.BufferGeometry().setFromPoints(
    Array.from({ length: n + 1 }, (_, i) => new THREE.Vector3(Math.cos((i / n) * Math.PI * 2) * r,
                                                                Math.sin((i / n) * Math.PI * 2) * r, 0)));
  g.userData.line = true;
  return g;
}

// Floor from y = -depth to 0, a quarter-circle of `radius` up to the wall, wall to `height`.
function cyclorama(m) {
  const prof = [[-m.depth, 0], [0, 0]];
  for (let i = 1; i <= m.segments; i++) {
    const t = (Math.PI / 2) * (i / m.segments);
    prof.push([m.radius * Math.sin(t), m.radius - m.radius * Math.cos(t)]);
  }
  prof.push([m.radius, m.height]);
  const x0 = -m.width / 2, x1 = m.width / 2;
  const pos = [], idx = [];
  prof.forEach(([y, z]) => pos.push(x0, y, z, x1, y, z));
  for (let i = 0; i + 1 < prof.length; i++) {
    const a = 2 * i;
    idx.push(a, a + 1, a + 3, a, a + 3, a + 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

// A rough head until Blender's real Suzanne arrives from `evaluate`.
function monkeyStandIn(size) {
  const g = new THREE.SphereGeometry(size * 0.42, 24, 16);
  g.scale(1.3, 0.9, 1);
  return g;
}

// Evaluated / explicit meshes: per-corner positions + normals (+ UVs) + triangle index;
// `triMat` (a slot per triangle) sorts the triangles into one group per material slot.
export function bufferGeometry({ positions, normals, uv, index, triMat }) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  if (normals) g.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
  if (uv) g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  if (triMat && triMat.length && triMat.some((x) => x)) {
    const slots = Math.max(...triMat) + 1, sorted = new Uint32Array(index.length);
    let at = 0;
    for (let slot = 0; slot < slots; slot++) {
      const start = at;
      for (let t = 0; t < triMat.length; t++) {
        if (triMat[t] !== slot) continue;
        sorted[at++] = index[t * 3]; sorted[at++] = index[t * 3 + 1]; sorted[at++] = index[t * 3 + 2];
      }
      if (at > start) g.addGroup(start, at - start, slot);
    }
    index = sorted;
    g.userData.slots = slots;
  }
  g.setIndex(new THREE.BufferAttribute(index, 1));
  if (!normals) g.computeVertexNormals();
  g.computeBoundingSphere();
  return g;
}

export function b64Floats(s) {
  const bin = atob(s);
  const buf = new ArrayBuffer(bin.length);
  const u8 = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return buf;
}
