/**
 * Examples gallery — the artifact derivation a shared chat opens by default,
 * the /examples fetch hook (one request, module-cached), and the cards.
 */
import { useRef, useState } from "react";
import { act, cleanup, render, renderHook, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, describe, test, expect, vi } from "vitest";
import { canvasArtifacts } from "../src/components/shared-view";
import { useExampleComposer, useExamples } from "../src/components/examples";
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

describe("useExampleComposer", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  function Harness() {
    const [input, setInput] = useState("");
    const ref = useRef<HTMLTextAreaElement>(null);
    const ex = useExampleComposer(input, setInput, ref);
    return (
      <>
        <textarea ref={ref} value={input} onChange={(e) => setInput(e.target.value)} placeholder={ex.hint} />
        <button onClick={() => ex.makeLike("A budget for [salary] SAR")}>budget</button>
        <button onClick={() => ex.makeLike("A deck about [topic]")}>deck</button>
        <button onClick={() => ex.setFormat("xlsx")}>excel</button>
      </>
    );
  }

  test("a chosen type has the composer ask its question", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("excel"));
    expect(screen.getByRole("textbox").getAttribute("placeholder")).toBe("What do you want to calculate or track?");
  });

  test("a draft that arrives with blanks (a Make one like this link) has its first blank selected", async () => {
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
    function Arrived() {
      const [input, setInput] = useState("A deck about [topic] for [audience]");
      const ref = useRef<HTMLTextAreaElement>(null);
      useExampleComposer(input, setInput, ref);
      return <textarea ref={ref} value={input} onChange={(e) => setInput(e.target.value)} />;
    }
    render(<Arrived />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    await waitFor(() => expect([box.selectionStart, box.selectionEnd]).toEqual([13, 20]));
  });

  test("a ?draft= link becomes the composer's draft, never a message sent, and leaves the address", async () => {
    const { keepDraftFromUrl } = await import("../src/lib/draft");
    sessionStorage.clear();
    window.history.replaceState({}, "", "/?draft=" + encodeURIComponent("أبي عرض عن [الموضوع]") + "&lang=ar");
    keepDraftFromUrl();
    expect(sessionStorage.getItem("cycls_draft")).toBe("أبي عرض عن [الموضوع]");
    expect(window.location.search).toBe("?lang=ar");
    window.history.replaceState({}, "", "/");
  });

  test("a template fills an empty composer with its first blank selected, replaces the template before it, never what the person wrote", async () => {
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
    render(<Harness />);
    const box = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.click(screen.getByText("budget"));
    expect(box.value).toBe("A budget for [salary] SAR");
    await waitFor(() => expect([box.selectionStart, box.selectionEnd]).toEqual([13, 21]));
    fireEvent.click(screen.getByText("deck"));
    expect(box.value).toBe("A deck about [topic]");
    fireEvent.change(box, { target: { value: "my own words" } });
    fireEvent.click(screen.getByText("budget"));
    expect(box.value).toBe("my own words");
  });
});

describe("example cards", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete (navigator as { pdfViewerEnabled?: boolean }).pdfViewerEnabled;
  });
  type Item = { share: string; title: string; prompt: string; file: { path: string; name: string; url: string } | null; thumbnail?: string; kind?: string; template?: string };
  const item = (n: number, file: Item["file"] = null): Item => ({
    share: `/shared/u/t${n}?example=1`, title: `T${n}`, prompt: `أبغى ميزانية شهرية رقم ${n}`, file,
  });
  let observers: { cb: IntersectionObserverCallback; el: Element }[] = [];
  // `near`: the cards are on screen, so they load what they show.
  const gallery = async (items: Item[], near = false, categories = [{ label: "Sheets", items }]) => {
    vi.resetModules();   // the gallery keeps what it fetched for the visit: a fresh one each test
    observers = [];
    vi.stubGlobal("IntersectionObserver", class {
      constructor(private cb: IntersectionObserverCallback) {}
      observe(el: Element) {
        observers.push({ cb: this.cb, el });
        if (near) this.cb([{ isIntersecting: true } as IntersectionObserverEntry], this as never);
      }
      disconnect() {}
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ categories }) }));
    const { ExamplesGallery } = await import("../src/components/examples");
    const onUsePrompt = vi.fn();
    render(<ExamplesGallery onUsePrompt={onUsePrompt} />);
    await waitFor(() => expect(shares().length).toBeGreaterThan(0));
    return onUsePrompt;
  };
  // The examples the cards open, once each, in order: the tile and the words under it both open it.
  const shares = () => [...new Set([...document.querySelectorAll("a[href]")].map((a) => a.getAttribute("href")))];

  test("a card opens the example; Make one like this hands the composer its request", async () => {
    const onUsePrompt = await gallery([item(1)]);
    expect(shares()).toEqual(["/shared/u/t1?example=1"]);
    expect(screen.getByText("T1")).toBeTruthy();
    expect(screen.getByText("أبغى ميزانية شهرية رقم 1")).toBeTruthy();
    fireEvent.click(screen.getByText("Make one like this"));
    expect(onUsePrompt).toHaveBeenCalledWith("أبغى ميزانية شهرية رقم 1");
  });

  test("its template, blanks and all, goes before the request it came from", async () => {
    const onUsePrompt = await gallery([{ ...item(1), template: "A budget for a [salary] salary" } as Item]);
    fireEvent.click(screen.getByText("Make one like this"));
    expect(onUsePrompt.mock.calls[0][0]).toBe("A budget for a [salary] salary");
  });

  test("a PDF where the browser has no viewer of its own is its type and prompt, never the browser's placeholder", async () => {
    Object.defineProperty(navigator, "pdfViewerEnabled", { value: false, configurable: true });
    await gallery([item(1, { path: "r/report.pdf", name: "report.pdf", url: "/share/u/t1/file/r/report.pdf" })]);
    expect(screen.getAllByText("PDF").length).toBeGreaterThan(0);
    expect(screen.getByText("أبغى ميزانية شهرية رقم 1")).toBeTruthy();
    expect(document.querySelector("iframe")).toBeNull();
  });

  test("a card with a thumbnail shows that picture, its type from `kind`, and its file is never fetched", async () => {
    const deck = { path: "q3.pptx", name: "q3.pptx", url: "/share/u/t1/file/q3.pptx" };
    await gallery([{ ...item(1, null), thumbnail: "https://cms.cycls.ai/files/q3-cover.png", kind: "pptx" }, { ...item(2, deck), thumbnail: "https://cms.cycls.ai/files/x.png" }], true);
    await waitFor(() => expect(document.querySelector("img")).toBeTruthy());
    expect([...document.querySelectorAll("img")].map((i) => i.getAttribute("src")).sort())
      .toEqual(["https://cms.cycls.ai/files/q3-cover.png", "https://cms.cycls.ai/files/x.png"]);
    expect(screen.getAllByText("PPTX").length).toBe(2);
    expect(vi.mocked(fetch).mock.calls.map(([u]) => String(u))).toEqual(["/examples"]);
  });

  test("a new order each visit", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    await gallery([item(1), item(2), item(3)]);
    expect(shares()).toEqual(["/shared/u/t2?example=1", "/shared/u/t3?example=1", "/shared/u/t1?example=1"]);
  });

  test("under the composer, the file types: one chosen shows its examples and tells the composer", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0.999);   // no reshuffle: the order as given
    const sheet = (n: number) => ({ ...item(n), kind: "xlsx" });
    const deck = (n: number) => ({ ...item(n), kind: "pptx" });
    vi.resetModules();
    const onFormat = vi.fn();
    observers = [];
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ categories: [{ label: "Work", items: [sheet(1), sheet(2), deck(3)] }] }) }));
    const { ExamplesGallery } = await import("../src/components/examples");
    const onUsePrompt = vi.fn();
    render(<ExamplesGallery onUsePrompt={onUsePrompt} onFormat={onFormat} />);
    await waitFor(() => expect(shares().length).toBe(3));
    expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "PowerPoint" }));
    expect(shares()).toEqual(["/shared/u/t3?example=1"]);
    expect(onFormat).toHaveBeenLastCalledWith("pptx");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(onFormat).toHaveBeenLastCalledWith(null);
    // Make one like this marks what it makes.
    fireEvent.click(screen.getAllByText("Make one like this")[0]);
    expect(screen.getByRole("button", { name: "Excel" }).getAttribute("aria-pressed")).toBe("true");
    expect(onFormat).toHaveBeenLastCalledWith("xlsx");
  });

  test("two rows first, two more each time the end of the grid comes into view", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0.999);
    const more = () => act(() => {
      const o = observers.filter((x) => x.el.hasAttribute("data-examples-more")).at(-1)!;
      o.cb([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
    // A phone: two a row, so four first.
    await gallery(Array.from({ length: 20 }, (_, i) => item(i + 1)));
    expect(shares().length).toBe(4);
    cleanup();
    // Where there is room: three a row, so six first, then twelve, eighteen, all twenty.
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener() {}, removeEventListener() {} }));
    await gallery(Array.from({ length: 20 }, (_, i) => item(i + 1)));
    expect(shares().length).toBe(6);
    more();
    expect(shares().length).toBe(12);
    more();
    more();
    expect(shares().length).toBe(20);
    expect(document.querySelector("[data-examples-more]")).toBeNull();
    vi.unstubAllGlobals();
  });
});
