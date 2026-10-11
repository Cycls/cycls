import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, cleanup, fireEvent, screen, act } from "@testing-library/react";
import { DeckView } from "../src/components/deck-view";
import { CanvasDoc } from "../src/components/canvas";
import { beside } from "../src/components/comments";
import { CommentsContext, CommentStore, forgetComments, onPage, placeOf, type CommentThread, type CommentsApi, type CommentsHost } from "../src/lib/comments";

// Comments on a design: a pin on a spot of a slide and the thread under it — read from
// the workspace every few seconds, written where the pin is clicked, and shown on the
// slide they belong to, wherever that slide is now.

const FIG = "designs/pitch.fig";
const manifest = (n: number, extra: Record<string, unknown> = {}) => JSON.stringify({
  count: n,
  slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,S${i + 1}`),
  sizes: Array.from({ length: n }, () => [1920, 1080]),
  names: ["cover", "agenda", "closing"].slice(0, n),
  titles: Array.from({ length: n }, () => ""),
  notes: Array.from({ length: n }, () => ""),
  fig: FIG,
  ...extra,
});

const SARA = { id: "user_1", name: "Sara" }, OMAR = { id: "user_2", name: "Omar" };
let seq = 0;
const thread = (over: Partial<CommentThread> = {}): CommentThread => {
  const n = ++seq;
  return { id: `t${n}`, n, frame: 0, frame_name: "cover", x: 960, y: 540, author: OMAR, text: `comment ${n}`,
           at: "2026-10-11T10:00:00+00:00", updated: "2026-10-11T10:00:00+00:00", resolved: false, replies: [], ...over };
};

// A workspace's comments, as the routes keep them.
function server(threads: CommentThread[] = []) {
  const state = { threads, rev: 1 };
  const api = {
    list: vi.fn(async (_path: string, version?: string) =>
      version === String(state.rev) ? { unchanged: true, version } : { threads: state.threads.slice(), version: String(state.rev), me: SARA.id }),
    add: vi.fn(async (_path: string, body: Record<string, unknown>) => {
      const made = thread({ ...(body as Partial<CommentThread>), author: { id: SARA.id, name: String(body.name) }, text: String(body.text) });
      delete (made as unknown as Record<string, unknown>).name;
      state.threads = [...state.threads, made];
      state.rev += 1;
      return { thread: made };
    }),
    change: vi.fn(async (_path: string, id: string, body: Record<string, unknown>) => {
      let found = state.threads.find((x) => x.id === id) ?? null;
      if (found && body.op === "reply") found = { ...found, resolved: false, replies: [...found.replies, { id: `r${++seq}`, author: SARA, text: String(body.text), at: found.at }] };
      if (found && body.op === "resolve") found = { ...found, resolved: true, resolved_by: SARA };
      if (found && body.op === "reopen") found = { ...found, resolved: false };
      if (found && body.op === "edit") found = { ...found, text: String(body.text) };
      if (body.op === "delete") found = null;
      state.threads = state.threads.flatMap((x) => (x.id !== id ? [x] : found ? [found] : []));
      state.rev += 1;
      return { thread: found };
    }),
  };
  return { api: api as unknown as CommentsApi & typeof api, state };
}

const settle = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });

function deck(api: CommentsApi, data = manifest(3), extra: Record<string, unknown> = {}) {
  const host: CommentsHost = { api, me: SARA, agent: "Super" };
  return (
    <CommentsContext.Provider value={host}>
      <DeckView data={data} path="designs/pitch.deck.json" {...extra} />
    </CommentsContext.Provider>
  );
}

// The stage is 1160×640 with the slide's picture drawn 960×540 inside it, at (100, 50):
// half the slide's own 1920×1080.
const PICTURE = { left: 100, top: 50, width: 960, height: 540 }, STAGE = { left: 0, top: 0, width: 1160, height: 640 };
const rect = (r: { left: number; top: number; width: number; height: number }) =>
  ({ ...r, x: r.left, y: r.top, right: r.left + r.width, bottom: r.top + r.height, toJSON: () => r }) as DOMRect;

beforeEach(() => {
  seq = 0;
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    if (this.tagName === "IMG" || this.getAttribute("data-testid") === "comment-target") return rect(PICTURE);
    if (this.getAttribute("data-testid") === "comment-layer") return rect(STAGE);
    return rect({ left: 0, top: 0, width: 0, height: 0 });
  });
});
afterEach(() => { cleanup(); forgetComments(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("where a comment is", () => {
  it("stays with its slide by name when the slides are reordered", () => {
    expect(placeOf({ frame: 0, frame_name: "cover" }, ["agenda", "cover"])).toBe(1);
    expect(placeOf({ frame: 1, frame_name: "gone" }, ["agenda", "cover"])).toBeNull();     // its slide was deleted: not the one in its place
    expect(placeOf({ frame: 0, frame_name: "renamed since" }, ["post"])).toBe(0);          // a page of one slide has them all
    expect(placeOf({ frame: 0, frame_name: "slide" }, ["slide", "slide"])).toBe(0);        // a name two slides share says nothing
    expect(placeOf({ frame: 2, frame_name: "slide" }, ["slide", "slide", "other"])).toBe(2);
    expect(placeOf({ frame: 5, frame_name: "gone" }, ["agenda", "cover"])).toBeNull();     // its slide is gone
    expect(placeOf({ frame: 1 }, ["a", "b"])).toBe(1);
  });

  it("is on the page it names — and a design of one page has them all", () => {
    const post = thread({ page: "Post" }), story = thread({ page: "Story" }), old = thread();
    expect(onPage([post, story, old], "Story", ["Post", "Story"])).toEqual([story]);
    expect(onPage([post, story, old], "Post", ["Post", "Story"])).toEqual([post, old]);    // one that names no page is on the first
    expect(onPage([post, story, old], "Renamed", ["Renamed"])).toEqual([post, story, old]);
  });
});

describe("the store", () => {
  it("asks again with the version it has, every few seconds while a design shows them", async () => {
    vi.useFakeTimers();
    const { api, state } = server([thread()]);
    const store = new CommentStore(FIG, { api });
    const stop = store.watch();
    await vi.advanceTimersByTimeAsync(0);
    expect(api.list).toHaveBeenLastCalledWith(FIG, undefined);
    expect(store.get().threads).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(api.list).toHaveBeenLastCalledWith(FIG, "1");                 // told "unchanged": what is shown stays
    expect(store.get().threads).toHaveLength(1);
    state.threads = [...state.threads, thread()];                        // a teammate comments
    state.rev = 2;
    await vi.advanceTimersByTimeAsync(5000);
    expect(store.get().threads).toHaveLength(2);
    stop();
    const asked = api.list.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20000);
    expect(api.list.mock.calls.length).toBe(asked);                      // nothing shows them: nothing is asked
  });

  it("shows what was written at once, then reads the list whole from the version it had", async () => {
    const { api, state } = server([thread()]);
    const store = new CommentStore(FIG, { api, me: SARA });
    await store.refresh();
    state.threads = [...state.threads, thread({ text: "a teammate's, made meanwhile" })];
    state.rev = 2;
    await store.add({ frame: 0, x: 10, y: 10 }, "mine");
    expect(api.add).toHaveBeenCalledWith(FIG, { frame: 0, x: 10, y: 10, text: "mine", name: "Sara" });
    await store.refresh();
    // Taking the newer version on the strength of one thread would have skipped the teammate's.
    expect(store.get().threads.map((x) => x.text)).toEqual(["comment 1", "a teammate's, made meanwhile", "mine"]);
  });

  it("keeps what is shown when the workspace is out of reach", async () => {
    const { api } = server([thread()]);
    const store = new CommentStore(FIG, { api });
    await store.refresh();
    api.list.mockRejectedValueOnce(new Error("offline"));
    await store.refresh();
    expect(store.get().threads).toHaveLength(1);
  });
});

describe("pins on a deck's slides", () => {
  it("shows the open comments of the slide in view, each on its spot", async () => {
    const { api } = server([thread({ x: 960, y: 540 }), thread({ frame: 1, frame_name: "agenda" }), thread({ resolved: true })]);
    render(deck(api));
    await settle();
    const [pin] = screen.getAllByTestId("comment-pin");
    expect(screen.getAllByTestId("comment-pin")).toHaveLength(1);         // not slide 2's, not the resolved one
    // The middle of the slide is the middle of its picture, wherever the picture sits on the stage.
    expect(pin.style.left).toBe("580px");
    expect(pin.style.top).toBe("320px");
    expect(screen.getByTestId("comments-count").textContent).toBe("2");
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "ArrowRight" });
    expect(screen.getAllByTestId("comment-pin")).toHaveLength(1);
    expect(screen.getByTestId("comment-pin").getAttribute("data-thread")).toBe("t2");
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "ArrowRight" });
    expect(screen.queryByTestId("comment-pin")).toBeNull();
  });

  it("a comment follows its slide when the slides were reordered", async () => {
    const { api } = server([thread({ frame: 0, frame_name: "cover" })]);
    render(deck(api, manifest(3, { names: ["agenda", "cover", "closing"] })));
    await settle();
    expect(screen.queryByTestId("comment-pin")).toBeNull();               // the cover is slide 2 now
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "ArrowRight" });
    expect(screen.getByTestId("comment-pin")).toBeTruthy();
  });

  it("marks the slides that have open comments, in the grid", async () => {
    const { api } = server([thread(), thread(), thread({ frame: 2, frame_name: "closing" })]);
    render(deck(api));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    expect(screen.getAllByTestId("slide-comments").map((el) => el.textContent)).toEqual(["2", "1"]);
  });

  it("comment mode pins a new comment where the slide is clicked", async () => {
    const { api } = server();
    render(deck(api));
    await settle();
    expect(screen.queryByTestId("comment-target")).toBeNull();            // off: the slide is paged and presented as before
    fireEvent.click(screen.getByRole("button", { name: "Add a comment" }));
    // A quarter across and half-way down the picture: (480, 540) of the slide's own 1920×1080.
    fireEvent.click(screen.getByTestId("comment-target"), { clientX: 100 + 240, clientY: 50 + 270 });
    expect(screen.getByTestId("comment-draft-pin").style.left).toBe("340px");
    const box = screen.getByPlaceholderText("Add a comment");
    fireEvent.change(box, { target: { value: "Make the headline bigger" } });
    await act(async () => { fireEvent.keyDown(box, { key: "Enter" }); });
    await settle();
    expect(api.add).toHaveBeenCalledWith(FIG, { frame: 0, frame_name: "cover", x: 480, y: 540, text: "Make the headline bigger", name: "Sara" });
    expect(screen.getByTestId("comment-pin").style.left).toBe("340px");   // it is there at once
    expect(screen.getByTestId("comment-thread").textContent).toContain("Make the headline bigger");   // and open, to go on
  });

  it("a comment on one page of several says which page", async () => {
    const { api } = server();
    render(deck(api, manifest(2, { pages: [{ name: "Post", frames: 2 }, { name: "Story", frames: 2 }], page: "Story" })));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Add a comment" }));
    fireEvent.click(screen.getByTestId("comment-target"), { clientX: 100, clientY: 50 });
    const box = screen.getByPlaceholderText("Add a comment");
    fireEvent.change(box, { target: { value: "hi" } });
    await act(async () => { fireEvent.keyDown(box, { key: "Enter" }); });
    expect(api.add.mock.calls[0][1]).toMatchObject({ page: "Story", frame: 0, x: 0, y: 0 });
  });

  it("C turns comment mode on and off; Escape leaves it — and never reaches the canvas", async () => {
    const { api } = server();
    const canvasEscape = vi.fn();
    window.addEventListener("keydown", canvasEscape);
    render(deck(api));
    await settle();
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "c" });
    expect(screen.getByTestId("comment-target")).toBeTruthy();
    fireEvent.click(screen.getByTestId("comment-target"), { clientX: 200, clientY: 200 });
    expect(screen.getByTestId("comment-new")).toBeTruthy();
    canvasEscape.mockClear();
    act(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
    expect(screen.queryByTestId("comment-new")).toBeNull();               // first the comment being written
    expect(screen.getByTestId("comment-target")).toBeTruthy();
    act(() => { document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
    expect(screen.queryByTestId("comment-target")).toBeNull();            // then comment mode
    expect(canvasEscape).not.toHaveBeenCalled();
    window.removeEventListener("keydown", canvasEscape);
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "C" });
    expect(screen.getByTestId("comment-target")).toBeTruthy();
  });

  it("typing a comment pages nothing and toggles nothing", async () => {
    const { api } = server();
    render(deck(api));
    await settle();
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "c" });
    fireEvent.click(screen.getByTestId("comment-target"), { clientX: 200, clientY: 200 });
    const box = screen.getByPlaceholderText("Add a comment");
    for (const key of ["c", "ArrowRight", " "]) fireEvent.keyDown(box, { key });
    expect(screen.getByTestId("deck-counter").textContent).toBe("1 / 3");
    expect(screen.getByTestId("comment-new")).toBeTruthy();
  });
});

describe("a thread", () => {
  it("opens beside its pin: read, answered, resolved", async () => {
    const { api } = server([thread({ text: "Make the headline bigger", replies: [{ id: "r0", author: SARA, text: "On it", at: "2026-10-11T10:05:00+00:00" }] })]);
    render(deck(api));
    await settle();
    fireEvent.click(screen.getByTestId("comment-pin"));
    const card = screen.getByTestId("comment-thread");
    expect(card.textContent).toContain("Omar");
    expect(card.textContent).toContain("Make the headline bigger");
    expect(card.textContent).toContain("On it");
    const reply = screen.getByPlaceholderText("Reply");
    fireEvent.change(reply, { target: { value: "Done" } });
    await act(async () => { fireEvent.keyDown(reply, { key: "Enter" }); });
    await settle();
    expect(api.change).toHaveBeenCalledWith(FIG, "t1", { op: "reply", text: "Done", name: "Sara" });
    expect(screen.getByTestId("comment-thread").textContent).toContain("Done");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Resolve" })); });
    await settle();
    expect(api.change).toHaveBeenLastCalledWith(FIG, "t1", { op: "resolve", name: "Sara" });
    expect(screen.getByRole("button", { name: "Resolved" })).toBeTruthy();  // still open to look at, marked done
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("comment-pin")).toBeNull();               // closed: a resolved comment leaves the slide
    expect(screen.queryByTestId("comments-count")).toBeNull();
  });

  it("only its author changes or removes a comment", async () => {
    const { api } = server([thread({ author: OMAR, text: "theirs", replies: [{ id: "r0", author: SARA, text: "mine", at: "2026-10-11T10:05:00+00:00" }] })]);
    render(deck(api));
    await settle();
    fireEvent.click(screen.getByTestId("comment-pin"));
    const [theirs, mine] = screen.getAllByTestId("comment-said");
    expect(theirs.querySelector("button[aria-label='More']")).toBeNull();
    fireEvent.click(mine.querySelector("button[aria-label='More']")!);
    await act(async () => { fireEvent.click(screen.getByText("Delete")); });
    await settle();
    expect(api.change).toHaveBeenCalledWith(FIG, "t1", { op: "delete", reply: "r0", name: "Sara" });
  });

  it("a comment by the agent carries the agent's name", async () => {
    const { api } = server([thread({ author: { id: "agent", name: "Agent", agent: true }, text: "I moved the logo" })]);
    render(deck(api));
    await settle();
    fireEvent.click(screen.getByTestId("comment-pin"));
    expect(screen.getByTestId("comment-thread").textContent).toContain("Super");
  });
});

describe("a thread's card", () => {
  it("sits beside its pin — or under it where there is no room — and never on it", () => {
    const card = { w: 288, h: 200 };
    expect(beside({ x: 100, y: 300 }, card, { w: 1000, h: 600 })).toEqual({ left: 136, top: 266 });   // to its right
    expect(beside({ x: 900, y: 300 }, card, { w: 1000, h: 600 })).toEqual({ left: 604, top: 266 });   // no room there: to its left
    // A docked pane is narrower than a card and a pin side by side (the card used to open over the pin).
    expect(beside({ x: 150, y: 100 }, card, { w: 430, h: 600 })).toEqual({ left: 134, top: 108 });    // under it
    expect(beside({ x: 150, y: 560 }, card, { w: 430, h: 600 })).toEqual({ left: 134, top: 324 });    // over it, at the foot
  });
});

describe("the list", () => {
  it("lists every thread; a row goes to its slide and opens it there", async () => {
    const { api } = server([thread({ text: "on the cover" }), thread({ frame: 2, frame_name: "closing", text: "on the closing" }),
                            thread({ resolved: true, text: "done with" })]);
    render(deck(api));
    await settle();
    expect(screen.queryByTestId("comments-list")).toBeNull();
    fireEvent.click(screen.getByTestId("comments-open"));
    const rows = screen.getAllByTestId("comment-row");
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringContaining("on the closing"), expect.stringContaining("on the cover")]);
    expect(rows[0].textContent).toContain("Slide 3");
    fireEvent.click(rows[0]);
    expect(screen.queryByTestId("comments-list")).toBeNull();
    expect(screen.getByTestId("deck-counter").textContent).toBe("3 / 3");
    expect(screen.getByTestId("comment-thread").textContent).toContain("on the closing");
    fireEvent.click(screen.getByTestId("comments-open"));
    fireEvent.click(screen.getByRole("button", { name: /^Resolved/ }));
    expect(screen.getAllByTestId("comment-row").map((r) => r.textContent)).toEqual([expect.stringContaining("done with")]);
  });

  it("hands the open comments to the agent: words in the composer, to send or change", async () => {
    const { api } = server([thread()]);
    const composed = vi.fn();
    window.addEventListener("cycls:compose", composed);
    render(deck(api));
    await settle();
    fireEvent.click(screen.getByTestId("comments-open"));
    expect(screen.getByTestId("comments-ask").textContent).toBe("Ask Super to address them");
    fireEvent.click(screen.getByTestId("comments-ask"));
    expect((composed.mock.calls[0][0] as CustomEvent).detail).toEqual({ text: `Address the open comments on ${FIG}` });
    expect(screen.queryByTestId("comments-list")).toBeNull();
    window.removeEventListener("cycls:compose", composed);
  });
});

describe("where there is nobody to comment as", () => {
  it("a shared deck has no pins, no buttons, and asks for nothing", async () => {
    const { api } = server([thread()]);
    render(<DeckView data={manifest(3)} path="designs/pitch.deck.json" />);
    await settle();
    expect(screen.queryByTestId("comment-buttons")).toBeNull();
    expect(screen.queryByTestId("comment-layer")).toBeNull();
    fireEvent.keyDown(screen.getByTestId("deck-view"), { key: "c" });
    expect(screen.queryByTestId("comment-target")).toBeNull();
    expect(api.list).not.toHaveBeenCalled();
  });
});

describe("a single design", () => {
  it("is commented on its picture, as slide 1 of its page", async () => {
    const { api } = server([thread({ frame: 0, frame_name: "post", x: 540, y: 540 })]);
    const one = JSON.stringify({ count: 1, slides: ["data:image/png;base64,P"], sizes: [[1080, 1080]], names: ["post"], fig: "designs/a.fig" });
    render(
      <CommentsContext.Provider value={{ api, me: SARA }}>
        <CanvasDoc file={{ path: "designs/a.fig", name: "a.fig" }} content={one} error={false} />
      </CommentsContext.Provider>,
    );
    await settle();
    expect(api.list).toHaveBeenCalledWith("designs/a.fig", undefined);
    expect(screen.getByTestId("comment-pin").style.left).toBe("580px");   // half of 1080 → half of the picture
    fireEvent.click(screen.getByRole("button", { name: "Add a comment" }));
    fireEvent.click(screen.getByTestId("comment-target"), { clientX: 100 + 960, clientY: 50 });
    const box = screen.getByPlaceholderText("Add a comment");
    fireEvent.change(box, { target: { value: "crop this" } });
    await act(async () => { fireEvent.keyDown(box, { key: "Enter" }); });
    expect(api.add).toHaveBeenCalledWith("designs/a.fig", { frame: 0, frame_name: "post", x: 1080, y: 0, text: "crop this", name: "Sara" });
  });
});
