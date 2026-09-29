// A hash of what the web bundle is built from, stamped into the built index.html
// (vite.config.ts) so CI can tell a stale committed bundle without rebuilding it:
// a rebuild on another OS gives other asset hashes, but this hash is the same on
// any checkout — text is read with LF line endings, whatever git wrote.
//
//   node scripts/src-hash.mjs                → print the hash of the sources
//   node scripts/src-hash.mjs --check <html> → fail unless <html> carries it
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const CLIENT = join(dirname(fileURLToPath(import.meta.url)), "..");
const INPUTS = ["src", "public", "index.html", "package-lock.json", "vite.config.ts", "tsconfig.json"];

function files(path) {
  if (!statSync(path).isDirectory()) return [path];
  return readdirSync(path).flatMap((name) => files(join(path, name)));
}

export function srcHash(root = CLIENT) {
  const hash = createHash("sha256");
  const paths = INPUTS.flatMap((p) => files(join(root, p)))
    .map((p) => relative(root, p).split(sep).join("/"))
    .sort();
  for (const rel of paths) {
    let data = readFileSync(join(root, rel));
    if (!data.includes(0)) data = Buffer.from(data.toString("latin1").replace(/\r\n/g, "\n"), "latin1");   // text: LF
    hash.update(rel).update("\0").update(data).update("\0");
  }
  return hash.digest("hex").slice(0, 16);
}

export const META = "cycls-src";

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const want = srcHash();
  const i = process.argv.indexOf("--check");
  if (i < 0) {
    console.log(want);
  } else {
    const html = readFileSync(process.argv[i + 1], "utf8");
    const got = new RegExp(`<meta name="${META}" content="([0-9a-f]+)"`).exec(html)?.[1];
    if (got !== want) {
      console.error(`The built web client is stale: it was built from ${got ?? "unknown sources"}, the sources are ${want}. Run \`cd client && npm run build\` and commit the theme.`);
      process.exit(1);
    }
    console.log(`web client bundle is current (${want})`);
  }
}
