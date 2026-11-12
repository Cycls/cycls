import { it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { Files } from "../src/components/files";
import type { FilesPanelProps } from "../src/components/chat";
import type { FileEntry } from "../src/hooks/use-files";

// A file shows the face of who edited it last; the face opens who made it and who changed it, an agent's change
// with a link back to its chat. A file with no record shows its date alone.

afterEach(cleanup);

const at = new Date().toISOString();
const entries: FileEntry[] = [
  { name: "plan.docx", type: "file", size: 2048, modified: at,
    created: { by: { id: "u_me", name: "Mohammed", you: true }, at, action: "created", agent: "super", chat: { id: "c1", title: "Café plan" } },
    edited: { by: { id: "u_sara", name: "Sara Alharbi" }, at, action: "edited" } },
  { name: "notes.md", type: "file", size: 10, modified: at },
];

it("puts the last editor's face on a file, and the face opens who created and edited it", async () => {
  const opened: string[] = [];
  const noop = async () => {};
  render(<Files {...({
    entries, path: "", loading: false, onNavigate() {}, onReload() {}, onUpload: noop, onMkdir: noop, onRename: noop,
    onDelete: noop, onOpenFile: async () => "", readFile: async () => "", searchFiles: async () => [], listFolders: async () => [],
    onOpenChat: (id: string) => opened.push(id),
    fileInfo: async () => ({ created: entries[0].created, edited: entries[0].edited, activity: [entries[0].edited!, entries[0].created!] }),
  } as unknown as FilesPanelProps)} />);
  expect(screen.getAllByTitle(/Sara Alharbi/)).toHaveLength(1);   // notes.md has no record: no face
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  expect(await screen.findByText("Last edited")).toBeTruthy();
  const chat = (await screen.findAllByText("Café plan"))[0];
  expect(chat.parentElement?.textContent).toBe("via Super in “Café plan”");
  fireEvent.click(chat);
  expect(opened).toEqual(["c1"]);
});
