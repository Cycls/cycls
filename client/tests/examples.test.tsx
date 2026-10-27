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
  afterEach(() => {
    cleanup();
    delete (navigator as { pdfViewerEnabled?: boolean }).pdfViewerEnabled;
  });
  const item = (n: number, file: { path: string; name: string; url: string } | null = null) => ({
    share: `/shared/u/t${n}?example=1`, title: `T${n}`, prompt: `أبغى ميزانية شهرية رقم ${n}`, file,
  });
  const gallery = async (items: ReturnType<typeof item>[]) => {
    vi.resetModules();   // the gallery keeps what it fetched for the visit: a fresh one each test
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ categories: [{ label: "Sheets", items }] }) }));
    const { ExamplesGallery } = await import("../src/components/examples");
    const onUsePrompt = vi.fn();
    render(<ExamplesGallery onUsePrompt={onUsePrompt} />);
    // Use prompt and View once a card, in the bar at its foot (always there on touch, on hover with a pointer).
    await waitFor(() => expect(screen.getAllByText("View").length).toBe(items.length));
    return onUsePrompt;
  };
  const shares = () => [...new Set(screen.getAllByText("View").map((a) => a.getAttribute("href")))];

  test("View opens the example, Use prompt fills the composer; a card with no file to draw is its prompt", async () => {
    const onUsePrompt = await gallery([item(1)]);
    expect(shares()).toEqual(["/shared/u/t1?example=1"]);
    expect(screen.getByText("أبغى ميزانية شهرية رقم 1")).toBeTruthy();
    fireEvent.click(screen.getAllByText("Use prompt")[0]);
    expect(onUsePrompt).toHaveBeenCalledWith("أبغى ميزانية شهرية رقم 1");
  });

  test("a PDF where the browser has no viewer of its own is its type and prompt, never the browser's placeholder", async () => {
    Object.defineProperty(navigator, "pdfViewerEnabled", { value: false, configurable: true });
    await gallery([item(1, { path: "r/report.pdf", name: "report.pdf", url: "/share/u/t1/file/r/report.pdf" })]);
    expect(screen.getByText("PDF")).toBeTruthy();
    expect(screen.getByText("أبغى ميزانية شهرية رقم 1")).toBeTruthy();
    expect(document.querySelector("iframe")).toBeNull();
  });

  test("a new order each visit", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    await gallery([item(1), item(2), item(3)]);
    expect(shares()).toEqual(["/shared/u/t2?example=1", "/shared/u/t3?example=1", "/shared/u/t1?example=1"]);
    vi.restoreAllMocks();
  });
});
