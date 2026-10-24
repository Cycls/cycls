import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MessageBubble } from "../src/components/message";
import { Gallery } from "../src/components/parts/gallery";
import { SourceChip } from "../src/components/parts/sources-part";
import { UpgradeContext, nearLimit, usedUp } from "../src/components/usage";
import type { Message, Part } from "../src/hooks/use-chat";

// What a message shows besides its words: the pictures a tool made, in a grid that opens the canvas, the frame
// of one still being made, the chip a tool's source wears, and the limit an agent reports.

beforeEach(() => { URL.revokeObjectURL = vi.fn(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const said = (parts: Part[]): Message => ({ role: "assistant", content: "", parts });
const pic = (n: number): Part => ({ type: "image", src: `https://img.test/${n}.png`, alt: `pic ${n}` });

describe("pictures", () => {
  it("one shows at its own size, with the caption an app gave it", () => {
    render(<Gallery items={[{ type: "image", src: "https://img.test/a.png", caption: "The cover" }]} />);
    expect(screen.getByRole("img").getAttribute("src")).toBe("https://img.test/a.png");
    expect(screen.getByText("The cover")).toBeTruthy();
  });

  it("several make a grid, and a file among them opens in the canvas", async () => {
    const open = vi.fn();
    const files = [1, 2, 3, 4].map((n): Part => ({ type: "step", id: `t${n}:file`, tool_name: "Canvas", step: `images/${n}.png`, ok: true }));
    render(<Gallery items={files} resolve={async (p) => `blob:${p}`} onOpenFile={open} />);
    await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(4));
    fireEvent.click(screen.getAllByRole("button")[2]);
    expect(open).toHaveBeenCalledWith("images/3.png");
  });

  it("a picture being made holds its frame, then shows itself in place of its step", async () => {
    const making: Part = { type: "step", id: "t1", tool_name: "image", step: "a cat on a roof", picture: "16:9" };
    const { rerender } = render(<MessageBubble message={said([making])} isStreaming />);
    expect(screen.getByText("Making the picture")).toBeTruthy();
    expect(screen.getByText("a cat on a roof")).toBeTruthy();

    const resolve = vi.fn(async () => "blob:cat");
    const made: Part = { type: "step", id: "t1:file", tool_name: "Canvas", step: "images/cat.png", ok: true };
    rerender(<MessageBubble message={said([making, made])} resolveMedia={resolve} />);
    expect(screen.queryByText("a cat on a roof")).toBeNull();
    await waitFor(() => expect(screen.getByRole("img").getAttribute("src")).toBe("blob:cat"));
    expect(resolve).toHaveBeenCalledWith("images/cat.png");
  });

  it("a shared chat, with no way into the workspace, keeps the file's card", () => {
    render(<MessageBubble message={said([{ type: "step", id: "t1:file", tool_name: "Canvas", step: "images/cat.png", ok: true }])} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("cat.png")).toBeTruthy();
  });
});

describe("the limit an agent reports", () => {
  const usage = (used: number): Part => ({ type: "usage", used, limit: 14, resets: "2027-01-01" });

  it("shows its line in the last fifth, and its note once nothing is left", () => {
    expect(nearLimit(usage(10))).toBe(false);
    expect(nearLimit(usage(11))).toBe(true);
    expect(usedUp(usage(13))).toBe(false);
    expect(usedUp(usage(14))).toBe(true);
  });

  it("is nothing in the reply until it is used up; then the reply is the note, and its button opens the plans", () => {
    const { rerender } = render(<MessageBubble message={said([usage(12), { type: "text", text: "Sure." }])} />);
    expect(screen.queryByText("Subscribe and keep going")).toBeNull();
    const upgrade = vi.fn();
    rerender(<UpgradeContext.Provider value={{ upgrade, agent: "Super" }}><MessageBubble message={said([{ ...usage(14), per: "month" }])} /></UpgradeContext.Provider>);
    expect(screen.getByText("Thanks for trying Super")).toBeTruthy();
    expect(screen.getByText(/You've used this month's 14 free messages, and we'd love to keep going with you\. They come back on 1 January\./)).toBeTruthy();
    fireEvent.click(screen.getByText("Subscribe and keep going"));
    expect(upgrade).toHaveBeenCalled();
  });
});

describe("a source's chip", () => {
  const law = { title: "Labor Law 1426H", url: "https://ncar.gov.sa/d/1", label: "Labor Law · Art. 77",
                quote: "Unless the contract specifies compensation…", status: "In force", note: "As amended by M/46" };

  it("says what the tool named it, and its card shows what the tool said about it", () => {
    render(<SourceChip source={law} />);
    const chip = screen.getByRole("link");
    expect(chip.textContent).toBe("Labor Law · Art. 77");
    fireEvent.mouseEnter(chip);
    for (const words of ["In force", "Unless the contract specifies compensation…", "As amended by M/46"]) expect(screen.getByText(words)).toBeTruthy();
  });

  it("without a label it is the site's name, as before", () => {
    render(<SourceChip source={{ title: "GDP", url: "https://www.reuters.com/a" }} />);
    expect(screen.getByRole("link").textContent).toBe("reuters.com");
  });

  it("on a phone the first tap opens the card, which carries the link", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q === "(hover: none)", addEventListener() {}, removeEventListener() {} }));
    const onOpen = vi.fn();
    render(<SourceChip source={law} onOpen={onOpen} />);
    const tap = fireEvent.click(screen.getByText("Labor Law · Art. 77"));
    expect(tap).toBe(false);   // the chip did not leave for the site
    expect(onOpen).not.toHaveBeenCalled();
    const open = screen.getByText("Open").closest("a")!;
    expect(open.getAttribute("href")).toBe("https://ncar.gov.sa/d/1");
    fireEvent.click(open);
    expect(onOpen).toHaveBeenCalled();
  });
});
