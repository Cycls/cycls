import { describe, it, expect, vi } from "vitest";
import { parseAnnouncements, onColor } from "../src/components/surfaces";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn(), setPerson: vi.fn(), flagsProvider: () => null }));

const payload = [
  { id: "rel-1", type: "modal", title: "What's new", title_ar: "الجديد",
    items: [{ title: "Apps", title_ar: "التطبيقات", body: "Build one", image: "/a.png" }, { nope: true }] },
  { id: "tip-1", type: "corner", tag: "New", tag_ar: "جديد", tag_color: "#FF5400", title: "Try the canvas", body: "It opens as you write", cta: "Show me", url: "/x" },
  { id: "tip-2", type: "corner", tag: "Beta", tag_color: "red; background:url(x)", title: "Bad color" },
  { id: "old", type: "corner", title: "Gone", until: "2020-01-01" },
  { id: "soon", type: "corner", title: "Later", from: "2999-01-01" },
  { id: "bad", type: "toast", title: "Unknown type" },
  { type: "corner", title: "No id" },
  "junk",
];

describe("announcements from the flag payload", () => {
  it("keeps valid cards inside their window, in order", () => {
    const cards = parseAnnouncements(payload, new Set(), "en");
    expect(cards.map((c) => c.id)).toEqual(["rel-1", "tip-1", "tip-2"]);
    expect(cards[1].tagColor).toBe("#FF5400");
    expect(cards[2].tagColor).toBeUndefined();   // a color, never a stylesheet
    expect(cards[0].items).toEqual([{ title: "Apps", body: "Build one", image: "/a.png" }]);
    expect(cards[1].cta).toBe("Show me");
    expect(cards[1].tag).toBe("New");
  });

  it("drops what the person already saw", () => {
    expect(parseAnnouncements(payload, new Set(["rel-1", "tip-2"]), "en").map((c) => c.id)).toEqual(["tip-1"]);
  });

  it("localizes with a fallback to English", () => {
    const [modal, tip] = parseAnnouncements(payload, new Set(["tip-2"]), "ar");
    expect(modal.title).toBe("الجديد");
    expect(modal.items?.[0].title).toBe("التطبيقات");
    expect(tip.title).toBe("Try the canvas");
    expect(tip.tag).toBe("جديد");
  });

  it("accepts the {announcements: [...]} wrapper and rejects the rest", () => {
    expect(parseAnnouncements({ announcements: payload.slice(0, 1) }, new Set(), "en")).toHaveLength(1);
    expect(parseAnnouncements("nope", new Set(), "en")).toEqual([]);
    expect(parseAnnouncements(null, new Set(), "en")).toEqual([]);
  });
});

describe("tag text over its color", () => {
  it("goes dark on light and light on dark", () => {
    expect(onColor("#FFD400")).toBe("#111");
    expect(onColor("#1d4ed8")).toBe("#fff");
    expect(onColor("#fff")).toBe("#111");
    expect(onColor("tomato")).toBe("#fff");
  });
});
