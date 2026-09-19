import { describe, it, expect } from "vitest";
import { mentionAt, mentionSuppressed } from "../src/components/input-box";
import { matchTokens } from "../src/hooks/use-files";

const at = (text: string) => mentionAt(text, text.length);

describe("mentionAt — when the picker opens", () => {
  it("opens at start of input and after whitespace", () => {
    expect(at("@rep")).toEqual({ query: "rep", start: 0 });
    expect(at("see @rep")).toEqual({ query: "rep", start: 4 });
    expect(at("see\n@rep")).toEqual({ query: "rep", start: 4 });
  });

  it("never opens inside an email address", () => {
    expect(at("mf@cycls.com")).toBeNull();
    expect(at("mail mf@cycls.com")).toBeNull();
    // \b would match between the "f" and the "@" — this is why the guard is (?:^|\s)
    expect(/\b@/.test("mf@cycls.com")).toBe(true);
  });

  it("does not open after punctuation", () => {
    expect(at("(@rep")).toBeNull();
    expect(at('"@rep')).toBeNull();
  });

  it("keeps the most recent @ when there are several", () => {
    expect(at("@one @two")).toEqual({ query: "two", start: 5 });
  });
});

describe("mentionAt — what the query may contain", () => {
  it("allows spaces so multi-word filenames are searchable", () => {
    expect(at("@سياسات التحول")).toEqual({ query: "سياسات التحول", start: 0 });
    expect(at("@quarterly report")?.query).toBe("quarterly report");
  });

  it("ends the session on a double space", () => {
    expect(at("@report  and then")).toBeNull();
    expect(at("@report  ")).toBeNull();
  });

  it("ends the session on a newline", () => {
    expect(at("@report\nnext line")).toBeNull();
  });

  it("stops tracking past the length cap", () => {
    expect(at("@" + "x".repeat(64))?.query).toHaveLength(64);
    expect(at("@" + "x".repeat(65))).toBeNull();
  });

  it("reports the @ offset so the insert replaces the whole query", () => {
    const text = "please read @my long name";
    const m = mentionAt(text, text.length)!;
    expect(text.slice(m.start)).toBe("@my long name");
  });
});

describe("matchTokens — the old-server fallback filter", () => {
  const path = "docs/سياسات التحول الرقمي.docx";

  it("matches tokens in any order", () => {
    expect(matchTokens(path, ["سياسات", "الرقمي"])).toBe(true);
    expect(matchTokens(path, ["الرقمي", "سياسات"])).toBe(true);
  });

  it("matches on a single fragment", () => {
    expect(matchTokens(path, ["سياسات"])).toBe(true);
  });

  it("rejects when any token is missing", () => {
    expect(matchTokens(path, ["سياسات", "missing"])).toBe(false);
  });

  it("is case-insensitive and matches folder segments", () => {
    expect(matchTokens("Docs/Report.TXT", ["docs", "report"])).toBe(true);
  });
});


describe("session latch — the bug that killed the picker", () => {
  const step = (text: string, dead: { start: number; query: string } | null, hits: string[]) => {
    const mention = mentionAt(text, text.length)!;
    if (mentionSuppressed(mention, dead)) return { dead, queried: false };
    // Only a query that searched for something may latch.
    return { dead: !hits.length && mention.query.trim() ? { start: mention.start, query: mention.query } : dead, queried: true };
  };

  it("a bare @ must not latch the session shut", () => {
    // "@" yields a blank query. Latching on it made every later keystroke
    // suppressed, because "r".startsWith("") is true.
    let dead: { start: number; query: string } | null = null;
    ({ dead } = step("@", dead, []));
    expect(dead).toBeNull();
    expect(step("@r", dead, ["report.docx"]).queried).toBe(true);
  });

  it("latches on a real query that found nothing, and stays dead as it grows", () => {
    let dead: { start: number; query: string } | null = null;
    ({ dead } = step("@zzz", dead, []));
    expect(dead).toEqual({ start: 0, query: "zzz" });
    expect(step("@zzzz", dead, []).queried).toBe(false);
  });

  it("revives when you backspace to a query that had hits", () => {
    const dead = { start: 0, query: "reportx" };
    expect(step("@report", dead, ["report.docx"]).queried).toBe(true);
  });

  it("a blank dead query shuts the whole session — Esc only", () => {
    expect(mentionSuppressed({ start: 0, query: "anything" }, { start: 0, query: "" })).toBe(true);
  });

  it("a new @ elsewhere is a fresh session", () => {
    const dead = { start: 0, query: "zzz" };
    expect(mentionSuppressed({ start: 9, query: "zzz" }, dead)).toBe(false);
  });
});
