import { test, expect, vi } from "vitest";
import { render, within, waitFor } from "@testing-library/react";
import { TextPart } from "../src/components/parts/text-part";
import { createEditor } from "lexical";
import { $convertFromMarkdownString, $convertToMarkdownString } from "@lexical/markdown";
import MdEditor, { NODES, MARKDOWN } from "../src/components/md-editor";

const MD = [
  "# خطة الربع",
  "### Next steps",
  "فقرة **مهمة** و*مائلة* و~~محذوفة~~ مع `code`.",
  "An *English* paragraph with a [link](https://cycls.com).",
  "- أولاً\n- second",
  "1. one\n2. two",
  "- [ ] مهمة\n- [x] done",
  "> اقتباس",
  "| الاسم | Role |\n| --- | --- |\n| سارة | Designer |\n| Ali | **مهندس** |",
  "---",
  "![الشعار](media/logo.png)",
  "![demo](media/clip.mp4)",
  "![shot](media/x-(1600×900).png)",
  "```\ncode\n```",
].join("\n\n");

test("markdown comes out of the editor as it went in", () => {
  const editor = createEditor({ nodes: NODES, onError: (e) => { throw e; } });
  editor.update(() => $convertFromMarkdownString(MD, MARKDOWN), { discrete: true });
  expect(editor.getEditorState().read(() => $convertToMarkdownString(MARKDOWN))).toBe(MD);
});

test("an image path with parentheses stays whole", () => {
  const editor = createEditor({ nodes: NODES, onError: (e) => { throw e; } });
  editor.update(() => $convertFromMarkdownString("![shot](media/x-(1600×900).png)", MARKDOWN), { discrete: true });
  const srcs = editor.getEditorState().read(() => [...editor.getEditorState()._nodeMap.values()]
    .filter((n) => n.getType() === "media").map((n) => (n as unknown as { __src: string }).__src));
  expect(srcs).toEqual(["media/x-(1600×900).png"]);
});

test("each block takes its direction from its own text", () => {
  // dir="auto": the browser reads each block's first strong letter, so Arabic blocks run
  // right to left and English ones left to right, independently.
  const { container } = render(<MdEditor value={MD} onChange={() => {}} />);
  const blocks = [...container.querySelectorAll('[contenteditable] > *:not(hr), [contenteditable] li')];
  expect(blocks.length).toBe(19);
  expect(new Set(blocks.map((el) => el.getAttribute("dir")))).toEqual(new Set(["auto"]));
});

test("the toolbar has every markdown control", () => {
  const { getByLabelText, getByRole } = within(render(<MdEditor value="" onChange={() => {}} />).container);
  for (const label of ["Undo", "Redo", "Bold", "Italic", "Strikethrough", "Code", "Link", "Bulleted list", "Numbered list", "Checklist", "Table", "Image or video", "Divider"])
    expect(getByLabelText(label)).toBeTruthy();
  const styles = [...(getByRole("combobox") as HTMLSelectElement).options].map((o) => o.textContent);
  expect(styles).toEqual(["Text", "Heading 1", "Heading 2", "Heading 3", "Quote", "Code block"]);
});

test("markdown the rich editor would flatten stays in the plain-text editor", async () => {
  const { PLAIN_MD } = await import("../src/components/canvas");
  for (const md of ["$$x^2$$", "price $a_1$ here", "a <br> b", "note[^1]"])
    expect(PLAIN_MD.test(md), md).toBe(true);
  for (const md of [MD, "| a | b |\n|---|---|\n| 1 | 2 |", "![logo](a.png)", "Costs 5 SAR.", "see <https://cycls.com>", "a | b in prose"])
    expect(PLAIN_MD.test(md), md).toBe(false);
});

test("markdown media: workspace files load with credentials, videos play, links load as they are", async () => {
  const resolve = vi.fn(async (path: string) => `blob:${path}`);
  const md = "![logo](media/a.png)\n\n![demo](/workspace/media/b.mp4)\n\n![web](https://cycls.com/x.png)";
  const { container } = render(<TextPart text={md} resolveMedia={resolve} />);
  await waitFor(() => expect(container.querySelector("video")?.getAttribute("src")).toBe("blob:media/b.mp4"));
  expect(container.querySelector('img[alt="logo"]')?.getAttribute("src")).toBe("blob:media/a.png");
  expect(container.querySelector('img[alt="web"]')?.getAttribute("src")).toBe("https://cycls.com/x.png");
  expect(resolve).toHaveBeenCalledTimes(2);
});

test("a document's media resolves beside it first, then from the workspace root", async () => {
  const { mediaResolver } = await import("../src/components/canvas");
  const seen: string[] = [];
  const open = async (path: string) => {
    seen.push(path);
    if (path !== "docs/media/a.png" && path !== "shared/logo.png") throw new Error("404");
    return `blob:${path}`;
  };
  const resolve = mediaResolver("docs/report.md", open);
  expect(await resolve("media/a.png")).toBe("blob:docs/media/a.png");
  expect(await resolve("shared/logo.png")).toBe("blob:shared/logo.png");   // written from the root
  expect(seen).toEqual(["docs/media/a.png", "docs/shared/logo.png", "shared/logo.png"]);
});
