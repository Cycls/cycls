import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, act, fireEvent } from "@testing-library/react";
import { ShareDialog, type ShareLinks } from "../src/components/share-dialog";
import { CanvasDoc } from "../src/components/canvas";

// Sharing a design. The Share popover offered "Create link" again for a file that was
// already shared, and the shared page of a design showed "Preview isn't available".

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
afterEach(cleanup);

describe("the Share popover", () => {
  const linksWith = (rows: { token: string; url: string; audience?: string }[]): ShareLinks & { revoke: ReturnType<typeof vi.fn> } => ({
    find: vi.fn(async () => rows),
    revoke: vi.fn(async () => {}),
  });

  it("shows the link a file already has, and removes it", async () => {
    const links = linksWith([{ token: "tok1", url: "/shared/u/tok1", audience: "public" }]);
    const onShare = vi.fn(async () => "https://x/new");
    render(<ShareDialog mode="file" onClose={() => {}} onShare={onShare} path="file/designs/a.fig" links={links} />);
    await settle();
    expect(links.find).toHaveBeenCalledWith("file/designs/a.fig");
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe(`${window.location.origin}/shared/u/tok1`);
    expect(screen.queryByText("Create link")).toBeNull();

    fireEvent.click(screen.getByText("Remove link"));
    await settle();
    expect(links.revoke).toHaveBeenCalledWith("tok1");
    expect(screen.getByText("Create link")).toBeTruthy();
    expect(onShare).not.toHaveBeenCalled();
  });

  it("offers to create one when there is none, then shows it", async () => {
    const links = linksWith([]);
    render(<ShareDialog mode="file" onClose={() => {}} onShare={async () => "https://x/made"} path="file/a.md" links={links} />);
    await settle();
    fireEvent.click(screen.getByText("Create link"));
    await settle();
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("https://x/made");
  });

  it("a link for one audience doesn't stand in for another", async () => {
    const links = linksWith([{ token: "tok1", url: "/shared/u/tok1", audience: "org:o1" }]);
    render(<ShareDialog mode="file" onClose={() => {}} onShare={async () => "x"} org={{ id: "o1", name: "Acme" }}
                        path="file/a.md" links={links} />);
    await settle();
    expect(screen.getByText("Create link")).toBeTruthy();            // nothing public yet
    fireEvent.click(screen.getByText(/Acme/));
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toContain("/shared/u/tok1");
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
    expect(openFile).toHaveBeenCalledWith("designs/launch.fig?as=png");
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
