#!/usr/bin/env bash
# Build the patched OpenPencil editor SPA to $1 (default /out).
#
# The editor is upstream open-pencil with Cycls patches (editor/patches):
#   - main.ts, App.vue, WorkspaceView.vue, pwa.ts, aliases.ts: replacements for the
#     upstream files of the same name (the app shell, without what Cycls doesn't use)
#   - cycls-bridge.ts + host.ts: the postMessage bridge to the Cycls host (load, save,
#     live agent edits, the "Super" cursor, new design, export, brand, theme)
#   - stubs/*: modules aliased over upstream ones (save, export, tabs, menus, AI…)
#   - edits.json: exact edits to upstream files, applied by apply-edits.ts — each one
#     must match exactly, or the build fails
#   - upstream.sha256: the upstream files the above replace or mirror, pinned by hash
#
# Pinned to a known-good SHA so it builds the same every time (upstream drifts).
# Override with OPENPENCIL_REF=<sha> (keep it in step with editor/Dockerfile's default);
# a new ref fails the hash check until every pinned file is reviewed again. Runs on Bun
# in a Linux container (the monorepo build fails on Windows) — normally via
# editor/Dockerfile.
set -euo pipefail

OUT="${1:-/out}"
REF="${OPENPENCIL_REF:-6cf1748e31a0e43d3794d43abbd003ce9caa3c6f}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# editor/Dockerfile hands over the source already fetched (a pinned tarball) and
# installed, via OP_DIR; run bare, this fetches it with git.
if [ -n "${OP_DIR:-}" ] && [ -f "${OP_DIR}/package.json" ]; then
  echo "== open-pencil source at ${OP_DIR} (pre-fetched) =="
  cd "${OP_DIR}"
else
  echo "== fetch open-pencil @ ${REF} =="
  mkdir -p /op && cd /op
  git init -q
  git remote add origin https://github.com/open-pencil/open-pencil
  git fetch -q --depth 1 origin "${REF}"
  git checkout -q FETCH_HEAD
fi

echo "== check upstream =="
# Every upstream file we replace, stub or mirror, pinned: a changed one fails here.
sha256sum -c --quiet "${HERE}/patches/upstream.sha256"

echo "== apply cycls patches =="
cp "${HERE}/patches/main.ts"            src/main.ts
cp "${HERE}/patches/App.vue"            src/App.vue
cp "${HERE}/patches/WorkspaceView.vue"  src/views/WorkspaceView.vue
cp "${HERE}/patches/aliases.ts"         vite/aliases.ts
cp "${HERE}/patches/pwa.ts"             vite/pwa.ts
cp "${HERE}/patches/cycls-theme.css"    src/cycls-theme.css          # Cycls design-system chrome override (imported by main.ts)
mkdir -p src/app/embed/stubs
cp "${HERE}/patches/cycls-bridge.ts"    src/app/embed/cycls-bridge.ts
cp "${HERE}/patches/host.ts"            src/app/embed/host.ts
cp "${HERE}/patches/figma-compat.js"    src/app/embed/figma-compat.js  # the service's script prelude (src/figma-compat.js)
cp "${HERE}/patches/stubs/"*            src/app/embed/stubs/
bun "${HERE}/apply-edits.ts" "${HERE}/patches/edits.json"

echo "== build =="
if [ -z "${EDITOR_FAST:-}" ]; then   # EDITOR_FAST=1: a dev container that already installed and built the packages
  bun install
  bun run build:packages
fi
bunx vite build

# Replace the OpenPencil brand marks (built into dist/brand) with the Cycls mark —
# no OpenPencil "P" in the chrome logo, loading screen, or favicon. White mark on
# the dark chrome; black mark for the browser-tab favicon.
for f in app-icon mark mark-dark mark-micro mark-micro-dark mark-mono mark-mono-dark; do
  cp "${HERE}/patches/cycls-mark.svg" "dist/brand/${f}.svg" 2>/dev/null || true
done
cp "${HERE}/patches/cycls-mark-light.svg" dist/brand/favicon.svg 2>/dev/null || true

echo "== check the build =="
# A self-destroying service worker (vite/pwa.ts), and no call to a local MCP server.
grep -q unregister dist/sw.js || { echo "✗ dist/sw.js doesn't remove the old service worker"; exit 1; }
if grep -rqF '127.0.0.1:7600' dist/assets; then echo "✗ the bundle still probes a local MCP server"; exit 1; fi

mkdir -p "${OUT}"
cp -r dist/* "${OUT}"/
echo "== editor build -> ${OUT} =="
