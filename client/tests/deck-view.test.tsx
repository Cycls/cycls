import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, fireEvent, screen, act } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { DeckView, parseDeck } from "../src/components/deck-view";
import { PresentMode } from "../src/components/present-mode";
import { slideKeyTarget, useSlideNav } from "../src/hooks/use-slide-nav";

// The deck viewer (a multi-slide Design render) and present mode. Present mode
// owns the keyboard: chat's global Escape closes the whole canvas, so the Escape
// that ends a presentation must never reach it.

const manifest = (n: number, extra: Record<string, unknown> = {}) => JSON.stringify({
  count: n,
  slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,S${i + 1}`),
  titles: Array.from({ length: n }, (_, i) => (i === 0 ? "Cover" : "")),
  notes: Array.from({ length: n }, (_, i) => (i === 0 ? "Welcome everyone" : "")),
  transitions: Array.from({ length: n }, () => "fade"),
  fig: "designs/pitch.fig",
  ...extra,
});

const key = (k: string, target: EventTarget = document.body) =>
  act(() => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("useSlideNav", () => {
  it("maps keys to slides, clamped to the deck", () => {
    expect(slideKeyTarget("ArrowRight", 0, 3)).toBe(1);
    expect(slideKeyTarget("ArrowRight", 2, 3)).toBe(2);
    expect(slideKeyTarget("ArrowLeft", 0, 3)).toBe(0);
    expect(slideKeyTarget("End", 0, 3)).toBe(2);
    expect(slideKeyTarget("Home", 2, 3)).toBe(0);
    expect(slideKeyTarget("x", 1, 3)).toBeNull();
  });

  it("keeps the active slide on a real slide when the deck shrinks", () => {
    const { result, rerender } = renderHook(({ n }) => useSlideNav(n), { initialProps: { n: 5 } });
    act(() => result.current.go(4));
    expect(result.current.active).toBe(4);
    rerender({ n: 2 });
    expect(result.current.active).toBe(1);        // was past the end → the last slide
  });
});

describe("DeckView", () => {
  it("shows the current slide, its notes, and pages", () => {
    render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" />);
    expect(screen.getByTestId("deck-counter").textContent).toBe("1 / 3");
    expect(screen.getByText("Welcome everyone")).toBeTruthy();
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "ArrowRight" });
    expect(screen.getByTestId("deck-counter").textContent).toBe("2 / 3");
  });

  it("switches to a grid and back to the slide picked", () => {
    const { container } = render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" />);
    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    const cards = container.querySelectorAll("img[alt^='Slide']");
    expect(cards.length).toBe(3);
    fireEvent.click(cards[2].closest("button")!);
    expect(screen.getByTestId("deck-counter").textContent).toBe("3 / 3");
  });

  it("clamps when a refetch has fewer slides", () => {
    const { rerender } = render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" />);
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "End" });
    rerender(<DeckView data={manifest(2)} path="designs/pitch.deck.json" />);
    expect(screen.getByTestId("deck-counter").textContent).toBe("2 / 2");
  });

  it("refetches when an agent edit lands on its .fig", () => {
    const onReload = vi.fn();
    render(<DeckView data={manifest(2)} path="designs/pitch.deck.json" onReload={onReload} />);
    act(() => { window.dispatchEvent(new CustomEvent("cycls:design-command", { detail: { path: "designs/other.fig" } })); });
    expect(onReload).not.toHaveBeenCalled();
    act(() => { window.dispatchEvent(new CustomEvent("cycls:design-command", { detail: { path: "designs/pitch.fig" } })); });
    expect(onReload).toHaveBeenCalledOnce();
  });

  it("downloads the whole deck on demand", async () => {
    const openFile = vi.fn(async () => "blob:deck");
    render(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={openFile} />);
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "PDF" })); });
    expect(openFile).toHaveBeenCalledWith("designs/pitch.deck.json?as=pdf");
  });

  it("the slides of one page of several download as that page", async () => {
    const openFile = vi.fn(async () => "blob:x");
    const paged = manifest(2, { pages: [{ name: "Post", frames: 1 }, { name: "Launch reel", frames: 2 }], page: "Launch reel" });
    render(<DeckView data={paged} path="designs/launch.fig" openFile={openFile} />);
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "PDF" })); });
    expect(openFile).toHaveBeenCalledWith("designs/launch.fig?as=pdf&page=Launch%20reel");
  });

  it("a carousel downloads as its images, offered first", async () => {
    const openFile = vi.fn(async () => "blob:zip");
    const square = manifest(2, { sizes: [[1080, 1080], [1080, 1080]] });
    render(<DeckView data={square} path="designs/reel.deck.json" openFile={openFile} />);
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    const items = ["Images (.zip)", "PowerPoint (.pptx)", "PDF"].map((name) => screen.getByRole("button", { name }));
    expect(items[0].compareDocumentPosition(items[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await act(async () => { fireEvent.click(items[0]); });
    expect(openFile).toHaveBeenCalledWith("designs/reel.deck.json?as=images");
    cleanup();

    render(<DeckView data={manifest(2, { sizes: [[1920, 1080], [1920, 1080]] })} path="designs/pitch.deck.json" openFile={openFile} />);
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    const [pptx, images] = ["PowerPoint (.pptx)", "Images (.zip)"].map((name) => screen.getByRole("button", { name }));
    expect(pptx.compareDocumentPosition(images) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();   // a deck: after
  });

  it("a document is pages, downloaded as a PDF first, and its pages aren't moved one by one", async () => {
    const openFile = vi.fn(async () => "blob:pdf");
    const onSlideOp = vi.fn(async () => {});
    const report = manifest(3, { kind: "document", sizes: [[1240, 1754], [1240, 1754], [1240, 1754]], fig: "designs/report.fig" });
    render(<DeckView data={report} path="designs/report.deck.json" openFile={openFile} onSlideOp={onSlideOp} />);
    expect(screen.getByRole("button", { name: "Pages" })).toBeTruthy();          // not "Slides"
    expect(screen.queryByRole("button", { name: "Slides" })).toBeNull();
    expect(screen.getByText("3 pages")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    const [pdf, pptx, images] = ["PDF", "PowerPoint (.pptx)", "Images (.zip)"].map((name) => screen.getByRole("button", { name }));
    expect(pdf.compareDocumentPosition(pptx) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(pptx.compareDocumentPosition(images) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();   // portrait, yet not a carousel
    await act(async () => { fireEvent.click(pdf); });
    expect(openFile).toHaveBeenCalledWith("designs/report.deck.json?as=pdf");
    // Its pages are numbered and listed in its contents: no drag, no duplicate / delete.
    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    expect(screen.queryByRole("button", { name: "Slide actions" })).toBeNull();
    expect(screen.getAllByTestId("grid-slide")[0].getAttribute("draggable")).toBe("false");
  });

  it("Edit is offered only with an editor and a workspace to write to", () => {
    const { rerender } = render(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={async () => "b"} />);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    rerender(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={async () => "b"}
                       writeFile={async () => {}} designEditorUrl="https://ed.example" />);
    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("Edit and Preview are one switch: into the editor, and back to the slides", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
    const onReload = vi.fn();
    render(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={async () => "blob:fig"}
                     writeFile={async () => {}} designEditorUrl="https://ed.example" onReload={onReload} />);
    const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");
    expect(pressed("Preview")).toBe("true");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Edit" })); });
    expect(document.querySelector("iframe")).toBeTruthy();
    expect(pressed("Edit")).toBe("true");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Preview" })); await new Promise((r) => setTimeout(r, 0)); });
    expect(screen.getByTestId("deck-view")).toBeTruthy();
    expect(document.querySelector("iframe")).toBeNull();
    expect(onReload).toHaveBeenCalled();                                    // the slides, as edited
    vi.unstubAllGlobals();
  });

  it("a deck's editor has Full screen too, on the editor's own box", async () => {
    // A deck opened in the viewer and switched to Edit had no way to full screen: the
    // button was only in the canvas header of a design opened as its .fig.
    vi.stubGlobal("fetch", vi.fn(async () => ({ arrayBuffer: async () => new Uint8Array([1]).buffer })));
    URL.revokeObjectURL = vi.fn();
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    const request = vi.fn(async () => {});
    Object.defineProperty(Element.prototype, "requestFullscreen", { configurable: true, value: request });
    try {
      render(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={async () => "blob:fig"}
                       writeFile={async () => {}} designEditorUrl="https://ed.example" />);
      expect(screen.queryByRole("button", { name: "Full screen" })).toBeNull();   // the viewer has Present for that
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Edit" })); });
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Full screen" })); });
      expect(request).toHaveBeenCalledOnce();
      expect(request.mock.instances[0]).toBe(document.querySelector("iframe")!.parentElement);   // the editor's box
    } finally {
      delete (document as unknown as Record<string, unknown>).fullscreenEnabled;
      delete (Element.prototype as unknown as Record<string, unknown>).requestFullscreen;
      vi.unstubAllGlobals();
    }
  });

  it("Present opens present mode on the current slide, and returns to where it ended", () => {
    render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" />);
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "ArrowRight" });
    fireEvent.click(screen.getByRole("button", { name: /Present/ }));
    expect(screen.getByTestId("present-counter").textContent).toBe("2 / 3");
    key("ArrowRight");
    key("Escape");
    expect(screen.queryByTestId("present-mode")).toBeNull();
    expect(screen.getByTestId("deck-counter").textContent).toBe("3 / 3");
  });

  it("the owner reorders by drag, duplicates and deletes (with a confirm) from the grid", async () => {
    const onSlideOp = vi.fn(async () => {});
    const onReload = vi.fn();
    render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" onSlideOp={onSlideOp} onReload={onReload} />);
    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    const cards = screen.getAllByTestId("grid-slide");
    const dt = { effectAllowed: "", setData: () => {}, getData: () => "" };
    fireEvent.dragStart(cards[2], { dataTransfer: dt });
    fireEvent.dragOver(cards[0], { dataTransfer: dt });
    await act(async () => { fireEvent.drop(cards[0], { dataTransfer: dt }); });
    expect(onSlideOp).toHaveBeenLastCalledWith({ op: "move", number: 3, to: 1 });
    expect(onReload).toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Slide actions" })[1]);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Duplicate" })); });
    expect(onSlideOp).toHaveBeenLastCalledWith({ op: "duplicate", number: 2 });
    fireEvent.click(screen.getAllByRole("button", { name: "Slide actions" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete slide 1?")).toBeTruthy();
    expect(onSlideOp).toHaveBeenCalledTimes(2);                     // nothing deleted until confirmed
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Delete" }).at(-1)!); });
    expect(onSlideOp).toHaveBeenLastCalledWith({ op: "delete", number: 1 });
  });

  it("a shared deck (no slide ops) shows no slide actions", () => {
    render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" />);
    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    expect(screen.queryByRole("button", { name: "Slide actions" })).toBeNull();
    expect(screen.getAllByTestId("grid-slide")[0].getAttribute("draggable")).toBe("false");
  });

  it("a bad manifest says so", () => {
    render(<DeckView data="not json" path="designs/pitch.deck.json" />);
    expect(screen.getByText("Couldn't show this deck.")).toBeTruthy();
    expect(parseDeck('{"slides":["a","b"]}')!.count).toBe(2);
  });
});

describe("PresentMode", () => {
  const deck = { slides: ["data:a", "data:b", "data:c"], notes: ["Say hi", "", ""], transitions: ["fade", "slide", "none"] };
  let chatEscape: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    // Chat's global handler: Escape closes the whole canvas (bubble phase, on window).
    chatEscape = vi.fn();
    window.addEventListener("keydown", chatEscape);
  });
  afterEach(() => window.removeEventListener("keydown", chatEscape));

  it("pages with the keyboard", () => {
    render(<PresentMode deck={deck} onClose={() => {}} />);
    const counter = () => screen.getByTestId("present-counter").textContent;
    expect(counter()).toBe("1 / 3");
    key("ArrowRight");
    expect(counter()).toBe("2 / 3");
    key(" ");
    expect(counter()).toBe("3 / 3");
    key("Home");
    expect(counter()).toBe("1 / 3");
    key("End");
    expect(counter()).toBe("3 / 3");
    expect(chatEscape).not.toHaveBeenCalled();            // nothing underneath saw a key
  });

  it("back from the end screen is the last slide, whichever key goes back", () => {
    for (const back of ["ArrowLeft", "ArrowUp", "PageUp", "Backspace"]) {
      render(<PresentMode deck={deck} start={2} onClose={() => {}} />);
      key("ArrowRight");
      expect(screen.getByText(/End of presentation/)).toBeTruthy();
      key(back);
      expect(screen.queryByText(/End of presentation/)).toBeNull();
      expect(screen.getByTestId("present-counter").textContent, back).toBe("3 / 3");
      key(back);
      expect(screen.getByTestId("present-counter").textContent, back).toBe("2 / 3");
      cleanup();
    }
  });

  it("Escape leaves present mode and never reaches the canvas", () => {
    const onClose = vi.fn();
    render(<PresentMode deck={deck} onClose={onClose} />);
    key("Escape");
    expect(onClose).toHaveBeenCalledOnce();
    expect(chatEscape).not.toHaveBeenCalled();
  });

  it("N shows the speaker notes, G the grid (Escape closes the grid first)", () => {
    const onClose = vi.fn();
    render(<PresentMode deck={deck} onClose={onClose} />);
    key("n");
    expect(screen.getByText("Say hi")).toBeTruthy();
    key("g");
    expect(screen.getByTestId("present-grid").querySelectorAll("img").length).toBe(3);
    key("Escape");
    expect(onClose).not.toHaveBeenCalled();
    key("Escape");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("opening the presenter window doesn't end the show, though the browser drops fullscreen for it", () => {
    let full: Element | null = null;
    Object.defineProperty(document, "fullscreenElement", { configurable: true, get: () => full });
    const fullscreen = (el: Element | null) => act(() => { full = el; document.dispatchEvent(new Event("fullscreenchange")); });
    const popup = { document: document.implementation.createHTMLDocument("presenter"), closed: false,
                    focus: vi.fn(), close: vi.fn(), addEventListener: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    const now = vi.spyOn(performance, "now").mockReturnValue(1_000);
    const onClose = vi.fn();
    try {
      render(<PresentMode deck={deck} onClose={onClose} />);
      fullscreen(screen.getByTestId("present-mode"));
      key("p");
      expect(open).toHaveBeenCalledOnce();
      fullscreen(null);                                   // Chrome leaves fullscreen for the new window
      expect(onClose).not.toHaveBeenCalled();
      expect(popup.close).not.toHaveBeenCalled();
      key("ArrowRight");
      expect(screen.getByTestId("present-counter").textContent).toBe("2 / 3");
      fullscreen(screen.getByTestId("present-mode"));
      now.mockReturnValue(60_000);
      fullscreen(null);                                   // later, the browser's own Esc still leaves
      expect(onClose).toHaveBeenCalledOnce();
    } finally {
      delete (document as unknown as Record<string, unknown>).fullscreenElement;
    }
  });

  it("clicking past the last slide ends, then leaves", () => {
    const onClose = vi.fn();
    render(<PresentMode deck={deck} start={2} onClose={onClose} />);
    const stage = screen.getByTestId("present-mode").firstElementChild as HTMLElement;
    fireEvent.click(stage);
    expect(screen.getByText(/End of presentation/)).toBeTruthy();
    fireEvent.click(stage);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
