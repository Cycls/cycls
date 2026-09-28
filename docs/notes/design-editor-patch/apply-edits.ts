// Exact edits to the upstream source, each one checked. An edit whose `find` doesn't
// occur exactly `count` times (default 1) fails the build, and so does a missing
// `expect` — an upstream change never slips through as a silent no-op, which is what
// the seds this replaced did. Run from the upstream root:
//   bun apply-edits.ts patches/edits.json
import { readFileSync, writeFileSync } from "node:fs";

type Edit = { file: string; why?: string; find?: string; replace?: string; count?: number; expect?: string[] };

const edits: Edit[] = JSON.parse(readFileSync(process.argv[2], "utf8"));
let failed = 0;
for (const e of edits) {
  let text: string;
  try {
    text = readFileSync(e.file, "utf8");
  } catch {
    console.error(`✗ ${e.file}: missing`);
    failed++;
    continue;
  }
  for (const s of e.expect ?? []) {
    if (!text.includes(s)) {
      console.error(`✗ ${e.file}: expected ${JSON.stringify(s.slice(0, 90))}`);
      failed++;
    }
  }
  if (e.find == null) continue;
  const found = text.split(e.find).length - 1, want = e.count ?? 1;
  if (found !== want) {
    console.error(`✗ ${e.file}: ${JSON.stringify(e.find.slice(0, 90))} occurs ${found}×, expected ${want}`);
    failed++;
    continue;
  }
  writeFileSync(e.file, text.split(e.find).join(e.replace ?? ""));
}
if (failed) {
  console.error(`${failed} edit(s) didn't apply — upstream changed; review editor/patches/edits.json`);
  process.exit(1);
}
console.log(`applied ${edits.length} edits`);
