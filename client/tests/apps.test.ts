import { describe, it, expect } from "vitest";
import { parseManifest, APPS_DIR } from "../src/hooks/use-apps";

describe("parseManifest", () => {
  it("uses the manifest when it is present", () => {
    const a = parseManifest(
      "burnup",
      JSON.stringify({ name: "Vendor burn-up", icon: "📈", description: "By vendor" }),
    );
    expect(a).toEqual({
      slug: "burnup",
      name: "Vendor burn-up",
      icon: "📈",
      letter: "V",
      description: "By vendor",
      entry: `${APPS_DIR}/burnup/index.html`,
    });
  });

  it("titleises the folder name when there is no manifest", () => {
    const a = parseManifest("vendor_burn-up", null);
    expect(a.name).toBe("Vendor Burn Up");
    expect(a.description).toBeUndefined();
  });

  it("degrades to the folder name rather than hiding a broken app", () => {
    for (const raw of ["{not json", "null", "[]", '"a string"', "42"]) {
      expect(parseManifest("burnup", raw).name, raw).toBe("Burnup");
    }
  });

  it("ignores non-string and blank fields", () => {
    const a = parseManifest("burnup", JSON.stringify({ name: 42, icon: "   ", description: {} }));
    expect(a.name).toBe("Burnup");
    expect(a.icon).toBeUndefined();
    expect(a.description).toBeUndefined();
  });

  it("caps field lengths so a manifest cannot break the list", () => {
    const a = parseManifest(
      "x",
      JSON.stringify({ name: "n".repeat(200), icon: "i".repeat(50), description: "d".repeat(500) }),
    );
    expect(a.name).toHaveLength(60);
    expect(a.description).toHaveLength(200);
  });
});

describe("app icons", () => {
  const icon = (v: unknown, slug = "burnup") =>
    parseManifest(slug, JSON.stringify({ name: "Vendor burn-up", icon: v }));

  it("falls back to the first letter of the name", () => {
    expect(parseManifest("burnup", null).letter).toBe("B");
    expect(icon(undefined).letter).toBe("V");
    const a = icon(undefined);
    expect(a.icon).toBeUndefined();
    expect(a.iconSrc).toBeUndefined();
    expect(a.iconFile).toBeUndefined();
  });

  it("takes the first letter by code point, so Arabic and emoji names work", () => {
    expect(parseManifest("x", JSON.stringify({ name: "إنجاز" })).letter).toBe("إ");
    expect(parseManifest("x", JSON.stringify({ name: "🚀 Launch" })).letter).toBe("🚀");
  });

  it("keeps an emoji as text", () => {
    expect(icon("📈").icon).toBe("📈");
    expect(icon("📈").iconSrc).toBeUndefined();
  });

  it("uses a data URI directly", () => {
    const a = icon("data:image/png;base64,AAAA");
    expect(a.iconSrc).toBe("data:image/png;base64,AAAA");
    expect(a.icon).toBeUndefined();
  });

  it("resolves an image file against the app's own folder", () => {
    for (const [given, want] of [
      ["logo.png", "apps/burnup/logo.png"],
      ["assets/mark.svg", "apps/burnup/assets/mark.svg"],
      ["/logo.webp", "apps/burnup/logo.webp"],
      ["photo.JPEG", "apps/burnup/photo.JPEG"],
    ]) {
      expect(icon(given).iconFile, given).toBe(want);
    }
  });

  it("refuses a remote image — an app icon cannot phone home", () => {
    for (const url of ["https://evil.com/x.png", "http://a/b.svg", "data:text/html,<b>"]) {
      const a = icon(url);
      expect(a.iconFile, url).toBeUndefined();
      expect(a.iconSrc, url).toBeUndefined();
    }
  });

  it("ignores a long or path-like string that is neither", () => {
    expect(icon("a/b/c").icon).toBeUndefined();
    expect(icon("not an emoji at all").icon).toBeUndefined();
    expect(icon("not an emoji at all").letter).toBe("V");
  });

  it("always points at index.html in the app's own folder", () => {
    expect(parseManifest("a-b", null).entry).toBe(`${APPS_DIR}/a-b/index.html`);
  });
});
