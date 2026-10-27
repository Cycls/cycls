/**
 * Examples gallery — the artifact derivation a shared chat opens by default,
 * and the /examples fetch hook (one request, module-cached).
 */
import { cleanup, render, renderHook, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, test, expect, vi } from "vitest";
import { canvasArtifacts } from "../src/components/shared-view";
import { useExamples } from "../src/components/examples";
import type { Message } from "../src/hooks/use-chat";

vi.mock("../src/lib/analytics", () => ({ track: vi.fn() }));

describe("canvasArtifacts", () => {
  test("collects successful Canvas steps in order, skipping errors and repeats", () => {
    const messages: Message[] = [
      { role: "user", content: "make a site" },
      {
        role: "assistant",
        content: "",
        parts: [
          { type: "step", tool_name: "Canvas", step: "draft.html" },
          { type: "step", tool_name: "Canvas", step: "broken.html", ok: false },
          { type: "step", tool_name: "Bash", step: "ls" },
          { type: "step", tool_name: "Canvas", step: "site.html" },
          { type: "step", tool_name: "Canvas", step: "site.html" }, // retry — same file
        ],
      },
    ];
    expect(canvasArtifacts(messages)).toEqual(["draft.html", "site.html"]);
  });

  test("empty for conversations without canvas output", () => {
    expect(canvasArtifacts([{ role: "user", content: "hi" }])).toEqual([]);
    expect(canvasArtifacts([{ role: "assistant", content: "hello", parts: [{ type: "text", text: "hello" }] }])).toEqual([]);
  });
});

describe("useExamples", () => {
  test("fetches /examples once and caches across mounts", async () => {
    const categories = [{ label: "Sites", items: [{ share: "/shared/u/t?example=1", title: "T", prompt: "p", file: null }] }];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ categories }) });
    vi.stubGlobal("fetch", fetchMock);

    const first = renderHook(() => useExamples());
    await waitFor(() => expect(first.result.current).toEqual(categories));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/examples");

    // A remount (every new chat) serves from the module cache — no refetch.
    const second = renderHook(() => useExamples());
    expect(second.result.current).toEqual(categories);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("example cards", () => {
  afterEach(cleanup);
  const item = (n: number) => ({
    share: `/shared/u/t${n}?example=1`, title: `T${n}`, prompt: `أبغى ميزانية شهرية رقم ${n}`,
    file: { path: `budget/budget-${n}.xlsx`, name: `budget-${n}.xlsx`, url: `/share/u/t${n}/file/budget/budget-${n}.xlsx` },
  });
  const gallery = async (items: ReturnType<typeof item>[]) => {
    vi.resetModules();   // the gallery keeps what it fetched for the visit: a fresh one each test
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ categories: [{ label: "Sheets", items }] }) }));
    const { ExamplesGallery } = await import("../src/components/examples");
    const onUsePrompt = vi.fn();
    render(<ExamplesGallery onUsePrompt={onUsePrompt} />);
    await waitFor(() => expect(screen.getAllByRole("link").length).toBe(items.length));
    return onUsePrompt;
  };

  test("a card is what was asked and the file it made, in text; it opens the example, Use prompt fills the composer", async () => {
    const onUsePrompt = await gallery([item(1)]);
    const card = screen.getByRole("link");
    expect(card.getAttribute("href")).toBe("/shared/u/t1?example=1");
    expect(card.textContent).toContain("أبغى ميزانية شهرية رقم 1");
    expect(card.textContent).toContain("budget-1.xlsx");
    expect(document.querySelector("iframe")).toBeNull();   // no live render of the file
    fireEvent.click(screen.getByText("Use prompt"));
    expect(onUsePrompt).toHaveBeenCalledWith("أبغى ميزانية شهرية رقم 1");
  });

  test("a new order each visit", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    await gallery([item(1), item(2), item(3)]);
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(
      ["/shared/u/t2?example=1", "/shared/u/t3?example=1", "/shared/u/t1?example=1"]);
    vi.restoreAllMocks();
  });
});
