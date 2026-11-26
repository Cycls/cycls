import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, act, fireEvent } from "@testing-library/react";
import { ShareDialog, type ShareLinks } from "../src/components/share-dialog";
import { CanvasDoc } from "../src/components/canvas";

// Sharing: who can open it is one choice, "Only you" first. Choosing makes the link at once, changing who can
// open it keeps the same link, and "Only you" takes it back.

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
afterEach(cleanup);

describe("the Share popover", () => {
  const linksWith = (rows: { token: string; url: string; audience?: string }[]) => ({
    find: vi.fn(async () => rows),
    revoke: vi.fn(async () => {}),
    change: vi.fn(async () => {}),
  }) satisfies ShareLinks;
  const chosen = () => screen.getAllByRole("radio").find((r) => r.getAttribute("aria-checked") === "true")?.textContent;

  it("shows the card a file's link has, and Only you takes it back", async () => {
    const links = linksWith([{ token: "tok1", url: "/shared/u/tok1", audience: "public" }]);
    const onShare = vi.fn(async () => "https://x/new");
    render(<ShareDialog mode="file" onClose={() => {}} onShare={onShare} path="file/designs/a.fig" links={links} />);
    await settle();
    expect(links.find).toHaveBeenCalledWith("file/designs/a.fig");
    expect(chosen()).toBe("Anyone");
    expect(document.querySelector("img")?.getAttribute("src")).toBe(`${window.location.origin}/share/u/tok1/card.png`);
    expect(screen.getByText("Copy link")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: /Only you/ }));
    await settle();
    expect(links.revoke).toHaveBeenCalledWith("tok1");
    expect(chosen()).toBe("Only you");
    expect(screen.queryByText("Copy link")).toBeNull();
    expect(onShare).not.toHaveBeenCalled();
  });

  it("choosing who can open it makes the link at once", async () => {
    const onShare = vi.fn(async () => "https://x/made");
    render(<ShareDialog onClose={() => {}} onShare={onShare} />);
    expect(chosen()).toBe("Only you");
    fireEvent.click(screen.getByRole("radio", { name: /Anyone/ }));
    await settle();
    expect(onShare).toHaveBeenCalledWith("public");
    expect(screen.getByText("Copy link")).toBeTruthy();
    expect(screen.getByText(/Anyone with link can open the chat/)).toBeTruthy();
  });

  it("changing who can open it keeps the same link", async () => {
    const links = linksWith([{ token: "tok1", url: "/shared/u/tok1", audience: "org:o1" }]);
    const onShare = vi.fn(async () => "x");
    render(<ShareDialog mode="file" onClose={() => {}} onShare={onShare} org={{ id: "o1", name: "Acme" }} path="file/a.md" links={links} />);
    await settle();
    expect(chosen()).toBe("Acme");
    fireEvent.click(screen.getByRole("radio", { name: /Anyone/ }));
    await settle();
    expect(links.change).toHaveBeenCalledWith("tok1", "public");
    expect(chosen()).toBe("Anyone");
    expect(onShare).not.toHaveBeenCalled();
  });
});

describe("a design where there's no editor to open it in (a shared page)", () => {
  const fig = { path: "designs/launch.fig", name: "launch.fig" };
  const manifest = (n: number) => JSON.stringify({
    count: n, slides: Array.from({ length: n }, (_, i) => `data:image/jpeg;base64,S${i + 1}`), sizes: Array(n).fill([1080, 1080]) });

  it("shows as its picture, with the image to download", async () => {
    const openFile = vi.fn(async () => "blob:png");
    render(<CanvasDoc file={fig} content={manifest(1)} error={false} shared openFile={openFile} />);
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,S1");
    expect(screen.queryByText(/Preview isn't available/)).toBeNull();
    await act(async () => { fireEvent.click(screen.getByText("Download image")); });
    expect(openFile).toHaveBeenCalledWith("designs/launch.fig?as=png&download=1");
    await act(async () => { fireEvent.click(screen.getByText("Download PDF")); });
    expect(openFile).toHaveBeenCalledWith("designs/launch.fig?as=pdf&download=1");
  });

  it("a design of several pages shows a page at a time, each with its own downloads", async () => {
    const pages = [{ name: "Post", frames: 1 }, { name: "Story", frames: 1 }];
    const of = (page: string) => JSON.stringify({ count: 1, slides: [`data:image/jpeg;base64,${page}`], pages, page });
    const readFile = vi.fn(async () => of("Story"));
    const openFile = vi.fn(async () => "blob:png");
    render(<CanvasDoc file={fig} content={of("Post")} error={false} shared openFile={openFile} readFile={readFile} />);
    expect(screen.getAllByRole("tab").map((el) => el.textContent)).toEqual(["Post", "Story"]);
    await act(async () => { fireEvent.click(screen.getByText("Download image")); });
    expect(openFile).toHaveBeenLastCalledWith("designs/launch.fig?as=png&page=Post&download=1");
    await act(async () => { fireEvent.click(screen.getByRole("tab", { name: "Story" })); });
    expect(readFile).toHaveBeenCalledWith("designs/launch.fig?as=slides&page=Story", true);
    expect((screen.getByTestId("design-picture") as HTMLImageElement).src).toBe("data:image/jpeg;base64,Story");
    await act(async () => { fireEvent.click(screen.getByText("Download PDF")); });
    expect(openFile).toHaveBeenLastCalledWith("designs/launch.fig?as=pdf&page=Story&download=1");
  });

  it("with several frames, shows as a read-only deck", () => {
    render(<CanvasDoc file={fig} content={manifest(3)} error={false} shared openFile={async () => "b"} />);
    expect(screen.getByTestId("deck-counter").textContent).toBe("1 / 3");
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("falls back to the download card when there is no picture to show", () => {
    render(<CanvasDoc file={fig} content={null} error shared />);
    expect(screen.getByText(/Preview isn't available/)).toBeTruthy();
  });
});
