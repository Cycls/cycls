/**
 * The analytics contract is enforced, not aspirational: every event the
 * client can emit must be documented in docs/notes/analytics.md. Rename a
 * call site without the doc and this fails.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

function walk(dir: string, out: string[] = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(p);
  }
  return out;
}

describe("events contract", () => {
  it("every tracked event is documented in docs/notes/analytics.md", () => {
    const tracked = new Set<string>();
    for (const f of walk(join(__dirname, "../src"))) {
      for (const m of readFileSync(f, "utf8").matchAll(/\btrack\(\s*["']([a-z0-9_$]+)["']/g)) tracked.add(m[1]);
    }
    const doc = readFileSync(join(__dirname, "../../docs/notes/analytics.md"), "utf8");
    const documented = new Set([...doc.matchAll(/`([a-z][a-z0-9_]*)`/g)].map((m) => m[1]));
    const missing = [...tracked].filter((e) => !documented.has(e)).sort();
    expect(missing, `undocumented events: ${missing.join(", ")}`).toEqual([]);
    expect(tracked.size).toBeGreaterThan(40);   // the scan actually found the call sites
  });

  it("never mirrors a fact PostHog's SDK already observes", () => {
    // $pageview, $identify, $feature_flag_called, $survey_* — PostHog owns
    // these; a custom twin double-counts. Route a canonical event to another
    // destination if one needs the fact, never add it for PostHog's sake.
    const mirrors = ["page_view", "pageview", "page_viewed", "agent_open", "identify", "identified",
                     "session_start", "session_started", "login", "user_signed_in", "user_signed_up",
                     "feature_flag_called", "survey_shown", "survey_sent", "survey_dismissed"];
    const tracked = new Set<string>();
    for (const f of walk(join(__dirname, "../src"))) {
      for (const m of readFileSync(f, "utf8").matchAll(/\btrack\(\s*["']([a-z0-9_$]+)["']/g)) tracked.add(m[1]);
    }
    expect(mirrors.filter((e) => tracked.has(e))).toEqual([]);
  });
});
