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
