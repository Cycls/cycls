/**
 * urlKey — the match between a link the model typed and a URL a search
 * actually returned. It decides whether a link becomes a citation chip, so
 * it has to forgive cosmetic differences and nothing else.
 */
import { describe, test, expect } from "vitest";
import { urlKey, domainOf } from "../src/components/parts/sources-part";

describe("urlKey", () => {
  test("forgives scheme, www and a trailing slash", () => {
    const canonical = urlKey("https://www.reuters.com/world/middle-east/saudi-gdp/");
    for (const variant of [
      "http://reuters.com/world/middle-east/saudi-gdp",
      "https://reuters.com/world/middle-east/saudi-gdp/",
      "https://WWW.Reuters.com/world/middle-east/Saudi-GDP",
    ]) {
      expect(urlKey(variant)).toBe(canonical);
    }
  });

  test("a different page on the same host does NOT match", () => {
    expect(urlKey("https://reuters.com/a")).not.toBe(urlKey("https://reuters.com/b"));
    // The host alone isn't a citation for a specific article.
    expect(urlKey("https://reuters.com")).not.toBe(urlKey("https://reuters.com/a"));
  });

  test("query strings distinguish pages", () => {
    expect(urlKey("https://x.com/s?id=1")).not.toBe(urlKey("https://x.com/s?id=2"));
    expect(urlKey("https://x.com/s?id=1")).toBe(urlKey("http://www.x.com/s?id=1"));
  });

  test("a malformed URL degrades to a trimmed compare rather than throwing", () => {
    expect(() => urlKey("not a url")).not.toThrow();
    expect(urlKey("  Not A Url ")).toBe(urlKey("not a url"));
  });
});

describe("domainOf", () => {
  test("strips www and the scheme", () => {
    expect(domainOf("https://www.reuters.com/a/b")).toBe("reuters.com");
    expect(domainOf("https://argaam.com")).toBe("argaam.com");
  });

  test("falls back to something printable on a malformed URL", () => {
    expect(domainOf("nonsense")).toBe("nonsense");
  });
});
