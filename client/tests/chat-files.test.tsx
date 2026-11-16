import { render, screen, fireEvent, within } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { Files } from "../src/components/files";

// The open chat's files in the Files panel: marked where they are, first in their folder, and alone behind the filter.

test("a chat's folder is marked and first, and the filter shows its files alone", () => {
  const entries = [
    { name: "archive", type: "directory", size: 0, modified: "2026-11-01T00:00:00Z" },
    { name: "deck", type: "directory", size: 0, modified: "2026-11-10T00:00:00Z" },
    { name: "notes.md", type: "file", size: 5, modified: "2026-11-02T00:00:00Z" },
  ];
  const chatFiles = [{ path: "deck/launch.fig", by: { id: "u_me", you: true }, at: "2026-11-12T08:00:00Z", agent: "super" }];
  const props = { entries, path: "", loading: false, chatFiles, onNavigate: vi.fn(), onReload: vi.fn(), onUpload: vi.fn(), onMkdir: vi.fn(),
                  onRename: vi.fn(), onDelete: vi.fn(), onOpenFile: vi.fn(async () => ""), onOpenInCanvas: vi.fn() };
  render(<Files {...(props as never)} />);
  const names = screen.getAllByTitle(/archive|deck|notes\.md/).map((e) => e.getAttribute("title"));
  expect(names).toEqual(["deck", "archive", "notes.md"]);
  expect(screen.getByText("1 from this chat")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /From this chat/ }));
  expect(screen.queryByTitle("archive")).toBeNull();
  fireEvent.click(screen.getByTitle("deck/launch.fig"));
  expect(props.onOpenInCanvas).toHaveBeenCalledWith("deck/launch.fig", "launch.fig");
  expect(within(screen.getByRole("button", { name: /From this chat/ })).getByText("1")).toBeTruthy();
});
