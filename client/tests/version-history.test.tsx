import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, act, fireEvent, screen } from "@testing-library/react";
import { VersionHistory } from "../src/components/version-history";
import type { DesignHost } from "../src/components/design-editor-view";
import { InputBox } from "../src/components/input-box";

// A design's earlier versions: listed with what replaced each, restored (the open
// editor saves first and reopens after), or opened as a new design. And the
// composer's "Add selection": a button while a design has a selection, then a chip.

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

function host(): DesignHost & Record<string, ReturnType<typeof vi.fn>> {
  return {
    newDesign: vi.fn(), brand: vi.fn(), refreshFiles: vi.fn(), openInCanvas: vi.fn(),
    writeNew: vi.fn(async (p: string) => p),
    listVersions: vi.fn(async () => [
      { id: "20260929T120000-aaaaaa", at: minutesAgo(5), by: "agent", reason: "agent", intent: "move slide 4", size: 10 },
      { id: "20260929T110000-bbbbbb", at: minutesAgo(90), by: "user", reason: "save", size: 9 },
    ]),
    versionBlob: vi.fn(async () => new Blob(["OLD"])),
    restoreVersion: vi.fn(async () => ({ version: "v2" })),
  } as never;
}

describe("Version history", () => {
  afterEach(cleanup);

  it("lists what replaced each version, newest first", async () => {
    render(<VersionHistory path="designs/launch.fig" host={host()} onClose={() => {}} />);
    await flush();
    const rows = screen.getAllByTestId("design-version").map((r) => r.textContent ?? "");
    expect(rows[0]).toContain("Before an agent edit: move slide 4");
    expect(rows[0]).toContain("Agent");
    expect(rows[1]).toContain("Saved version");
    expect(rows[1]).toContain("You");
  });

  it("a change made in the deck viewer reads as a slide change, by the person", async () => {
    const h = host();
    h.listVersions = vi.fn(async () => [
      { id: "20260929T120000-cccccc", at: minutesAgo(1), by: "user", reason: "change", intent: "slide 3's notes", size: 10 }]) as never;
    render(<VersionHistory path="designs/launch.fig" host={h} onClose={() => {}} />);
    await flush();
    const [row] = screen.getAllByTestId("design-version").map((r) => r.textContent ?? "");
    expect(row).toContain("Before a slide change: slide 3's notes");
    expect(row).toContain("You");
    expect(row).not.toContain("agent");
  });

  it("Restore brings a version back and closes", async () => {
    const h = host();
    const onClose = vi.fn();
    render(<VersionHistory path="designs/launch.fig" host={h} onClose={onClose} />);
    await flush();
    fireEvent.click(screen.getAllByText("Restore")[1]);
    await flush();
    expect(h.restoreVersion).toHaveBeenCalledWith("designs/launch.fig", "20260929T110000-bbbbbb");
    expect(onClose).toHaveBeenCalled();
  });

  it("Preview shows what a version looks like before it is restored, and hides again", async () => {
    const h = host();
    (h as never as Record<string, unknown>).versionPreview = vi.fn(async () => new Blob(["PNG"], { type: "image/png" }));
    // (jsdom has no blob URLs: stand in for them.)
    const was = { make: URL.createObjectURL, free: URL.revokeObjectURL };
    const freed = vi.fn();
    (URL as never as Record<string, unknown>).createObjectURL = vi.fn(() => "blob:version-1");
    (URL as never as Record<string, unknown>).revokeObjectURL = freed;
    const { unmount } = render(<VersionHistory path="designs/launch.fig" host={h} onClose={() => {}} />);
    await flush();
    expect(screen.queryByRole("img")).toBeNull();                       // nothing is rendered until asked for
    fireEvent.click(screen.getAllByText("Preview")[1]);
    await flush();
    expect(h.versionPreview).toHaveBeenCalledWith("designs/launch.fig", "20260929T110000-bbbbbb");
    const img = screen.getByRole("img", { name: "This version" }) as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("blob:version-1");
    expect(screen.getAllByTestId("design-version")[1].contains(img)).toBe(true);   // in its own row, over its Restore
    expect(h.restoreVersion).not.toHaveBeenCalled();
    // Asked again, it is put away — and not fetched a second time when shown again.
    fireEvent.click(screen.getByText("Hide preview"));
    expect(screen.queryByRole("img")).toBeNull();
    fireEvent.click(screen.getAllByText("Preview")[1]);
    await flush();
    expect(h.versionPreview).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("img", { name: "This version" })).toBeTruthy();
    // Closed, the panel lets the picture go.
    unmount();
    expect(freed).toHaveBeenCalledWith("blob:version-1");
    URL.createObjectURL = was.make; URL.revokeObjectURL = was.free;
  });

  it("a version that can't be shown says so, and can still be restored", async () => {
    const h = host();
    (h as never as Record<string, unknown>).versionPreview = vi.fn(async () => { throw new Error("415"); });
    render(<VersionHistory path="designs/launch.fig" host={h} onClose={() => {}} />);
    await flush();
    fireEvent.click(screen.getAllByText("Preview")[0]);
    await flush();
    expect(screen.getByText("Couldn’t show that version.")).toBeTruthy();
    fireEvent.click(screen.getAllByText("Restore")[0]);
    await flush();
    expect(h.restoreVersion).toHaveBeenCalledWith("designs/launch.fig", "20260929T120000-aaaaaa");
  });

  it("without a way to make the picture there is no Preview", async () => {
    render(<VersionHistory path="designs/launch.fig" host={host()} onClose={() => {}} />);
    await flush();
    expect(screen.queryByText("Preview")).toBeNull();
  });

  it("Open as copy writes it as a new design beside this one, and opens it", async () => {
    const h = host();
    render(<VersionHistory path="designs/launch.fig" host={h} onClose={() => {}} />);
    await flush();
    fireEvent.click(screen.getAllByText("Open as copy")[0]);
    await flush();
    expect(h.versionBlob).toHaveBeenCalledWith("designs/launch.fig", "20260929T120000-aaaaaa");
    expect(h.writeNew).toHaveBeenCalledWith("designs/launch (earlier).fig", expect.any(Blob));
    expect(h.openInCanvas).toHaveBeenCalledWith("designs/launch (earlier).fig");
  });
});

describe("Add selection in the composer", () => {
  afterEach(cleanup);
  const base = {
    textareaRef: { current: null }, input: "", setInput: () => {}, handleKeyDown: () => {}, handleSubmit: () => {},
    isStreaming: false, onStop: () => {}, listening: false, transcribing: false,
    startMic: () => {}, stopMic: () => {}, cancelMic: () => {},
  };

  it("offers the button while a design has a selection", () => {
    const onAddSelection = vi.fn();
    render(<InputBox {...(base as never)} onAddSelection={onAddSelection} />);
    fireEvent.click(screen.getByTestId("add-selection"));
    expect(onAddSelection).toHaveBeenCalled();
  });

  it("shows the attached selection as a chip that can be removed", () => {
    const onRemoveSelection = vi.fn();
    render(<InputBox {...(base as never)} onRemoveSelection={onRemoveSelection}
                     selection={{ path: "designs/launch.fig", frame: "slide-1", nodes: [{ name: "headline", type: "TEXT" }, { name: "cta", type: "FRAME" }] }} />);
    expect(screen.getByTestId("selection-chip").textContent).toContain("launch.fig: headline, cta");
    expect(screen.queryByTestId("add-selection")).toBeNull();
    fireEvent.click(screen.getByLabelText("Remove selection"));
    expect(onRemoveSelection).toHaveBeenCalled();
  });
});
