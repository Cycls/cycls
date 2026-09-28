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

  it("Edit is offered only with an editor and a workspace to write to", () => {
    const { rerender } = render(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={async () => "b"} />);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    rerender(<DeckView data={manifest(2)} path="designs/pitch.deck.json" openFile={async () => "b"}
                       writeFile={async () => {}} designEditorUrl="https://ed.example" />);
    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
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
