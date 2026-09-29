// Copy the single-file build to where the SDK ships it.
import { copyFileSync, statSync } from "node:fs";
const dst = new URL("../../cycls/_agent/studio/app/index.html", import.meta.url);
copyFileSync(new URL("../dist/index.html", import.meta.url), dst);
const kb = Math.round(statSync(dst).size / 1024);
console.log(`studio → cycls/_agent/studio/app/index.html (${kb} KB)`);
if (kb > 1200) { console.error("over the 1.2 MB budget"); process.exit(1); }
