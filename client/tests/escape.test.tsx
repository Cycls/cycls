import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, act } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { DropdownMenu, InlineInput } from "../src/components/files";
import { ShareDialog } from "../src/components/share-dialog";
import { useEscape, useEscapeFallback } from "../src/hooks/use-escape";

// Chat's Escape closes the whole side pane (the canvas, the Files panel). With a menu,
// a popover or a dialog open inside it, Escape closed the pane too: the layer's own
// listener ran (or it had none), and then chat's.

const escape = (target: EventTarget = document.body) => act(async () => {
  target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 0));
});

// The pane as chat holds it, with something open inside.
function Pane({ children }: { children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(true);
  const [layer, setLayer] = useState(true);
  useEscapeFallback(() => setOpen(false), open);
  if (!open) return null;
  return <div data-testid="pane">{layer && children(() => setLayer(false))}</div>;
}

afterEach(cleanup);

describe("Escape closes one thing", () => {
  it("a dropdown menu, then the pane", async () => {
    render(<Pane>{(close) => (
      <div><button>menu</button><DropdownMenu items={[{ label: "Download", onClick: () => {} }]} onClose={close} /></div>
    )}</Pane>);
    expect(screen.getByText("Download")).toBeTruthy();
    await escape();
    expect(screen.queryByText("Download")).toBeNull();
    expect(screen.getByTestId("pane")).toBeTruthy();
    await escape();
    expect(screen.queryByTestId("pane")).toBeNull();
  });

  it("the Share popover, not the canvas under it", async () => {
    render(<Pane>{(close) => <ShareDialog mode="file" onClose={close} onShare={async () => "https://x/s"} />}</Pane>);
    expect(screen.getByText("Create link")).toBeTruthy();
    await escape();
    expect(screen.queryByText("Create link")).toBeNull();
    expect(screen.getByTestId("pane")).toBeTruthy();
  });

  it("the layer opened last, of two", async () => {
    const closed: string[] = [];
    function Layer({ name, children }: { name: string; children?: ReactNode }) {
      const [open, setOpen] = useState(true);
      useEscape(() => { closed.push(name); setOpen(false); }, open);
      return open ? <div>{name}{children}</div> : null;
    }
    function History() {   // a panel, and a menu opened from inside it
      const [menu, setMenu] = useState(false);
      return <Layer name="history"><button onClick={() => setMenu(true)}>more</button>{menu && <Layer name="menu" />}</Layer>;
    }
    render(<Pane>{() => <History />}</Pane>);
    act(() => screen.getByText("more").click());
    await escape();
    expect(closed).toEqual(["menu"]);
    await escape();
    expect(closed).toEqual(["menu", "history"]);
    expect(screen.getByTestId("pane")).toBeTruthy();
  });

  it("a rename field cancels its edit and keeps the pane", async () => {
    const onCancel = vi.fn();
    render(<Pane>{() => <InlineInput initial="deck" onSubmit={() => {}} onCancel={onCancel} />}</Pane>);
    await escape(screen.getByDisplayValue("deck"));
    expect(onCancel).toHaveBeenCalled();
    expect(screen.getByTestId("pane")).toBeTruthy();
  });
});
