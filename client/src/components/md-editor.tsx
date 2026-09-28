import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { LinkPlugin } from "@lexical/react/LexicalLinkPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { HorizontalRulePlugin } from "@lexical/react/LexicalHorizontalRulePlugin";
import { HorizontalRuleNode, $createHorizontalRuleNode, $isHorizontalRuleNode, INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/react/LexicalHorizontalRuleNode";
import { MarkdownShortcutPlugin } from "@lexical/react/LexicalMarkdownShortcutPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { LexicalTypeaheadMenuPlugin, MenuOption, useBasicTypeaheadTriggerMatch } from "@lexical/react/LexicalTypeaheadMenuPlugin";
import { DraggableBlockPlugin_EXPERIMENTAL } from "@lexical/react/LexicalDraggableBlockPlugin";
import { HeadingNode, QuoteNode, $createHeadingNode, $createQuoteNode, $isHeadingNode, $isQuoteNode, type HeadingTagType } from "@lexical/rich-text";
import {
  ListNode, ListItemNode, $isListNode, $isListItemNode, $insertList,
  INSERT_UNORDERED_LIST_COMMAND, INSERT_ORDERED_LIST_COMMAND, INSERT_CHECK_LIST_COMMAND, REMOVE_LIST_COMMAND,
} from "@lexical/list";
import { LinkNode, $isLinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import { CodeNode, $createCodeNode, $isCodeNode } from "@lexical/code-core";
import {
  TableNode, TableRowNode, TableCellNode, TableCellHeaderStates, INSERT_TABLE_COMMAND,
  $createTableNode, $createTableRowNode, $createTableCellNode, $isTableNode, $isTableRowNode, $isTableCellNode,
  $insertTableRowAtSelection, $insertTableColumnAtSelection, $deleteTableRowAtSelection, $deleteTableColumnAtSelection,
} from "@lexical/table";
import { $setBlocksType } from "@lexical/selection";
import { $findMatchingParent, mergeRegister } from "@lexical/utils";
import { $convertFromMarkdownString, $convertToMarkdownString, CHECK_LIST, TRANSFORMERS, type ElementTransformer, type TextMatchTransformer } from "@lexical/markdown";
import {
  $getSelection, $setSelection, $isRangeSelection, $createParagraphNode, $getNearestNodeFromDOMNode, $getRoot, $insertNodes,
  $applyNodeReplacement, createCommand, DecoratorNode, PASTE_COMMAND, DROP_COMMAND,
  FORMAT_TEXT_COMMAND, UNDO_COMMAND, REDO_COMMAND, CAN_UNDO_COMMAND, CAN_REDO_COMMAND, COMMAND_PRIORITY_LOW,
  type BaseSelection, type ElementNode, type LexicalEditor, type NodeKey, type SerializedLexicalNode, type Spread, type TextFormatType,
} from "lexical";
import { Media } from "./parts/media";
import { Icon } from "./icon";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

// Lazy-loaded (canvas.tsx): markdown in, markdown out, edited like Notion — "/" for blocks, a handle
// to drag them, tables. Every block is dir="auto", so Arabic and English paragraphs each run their own way.

// ![caption](media/photo.png) — or a video file, which plays. Inline, as markdown images are.
const MediaResolver = createContext<((path: string) => Promise<string>) | undefined>(undefined);
function MediaView({ src, alt }: { src: string; alt: string }) {
  return <Media src={src} alt={alt} resolve={useContext(MediaResolver)} />;
}
type SerializedMedia = Spread<{ src: string; alt: string }, SerializedLexicalNode>;
export class MediaNode extends DecoratorNode<React.JSX.Element> {
  __src: string;
  __alt: string;
  static getType() { return "media"; }
  static clone(node: MediaNode) { return new MediaNode(node.__src, node.__alt, node.__key); }
  static importJSON(json: SerializedMedia) { return $createMediaNode(json.src, json.alt); }
  constructor(src: string, alt = "", key?: NodeKey) { super(key); this.__src = src; this.__alt = alt; }
  exportJSON(): SerializedMedia { return { type: "media", version: 1, src: this.__src, alt: this.__alt }; }
  createDOM() { return document.createElement("span"); }
  updateDOM() { return false; }
  isInline() { return true; }
  decorate() { return <MediaView src={this.__src} alt={this.__alt} />; }
}
const $createMediaNode = (src: string, alt = "") => $applyNodeReplacement(new MediaNode(src, alt));
const $isMediaNode = (node: unknown): node is MediaNode => node instanceof MediaNode;

export const NODES = [HeadingNode, QuoteNode, ListNode, ListItemNode, LinkNode, CodeNode, HorizontalRuleNode,
  TableNode, TableRowNode, TableCellNode, MediaNode];

// The path may hold balanced parentheses — "shot-(1600×900).png" — or be <wrapped>, as in CommonMark.
const MEDIA_PATH = String.raw`(<[^>\n]*>|(?:[^()\s]|\([^()\s]*\))+)`;
const MEDIA: TextMatchTransformer = {
  dependencies: [MediaNode],
  export: (node) => ($isMediaNode(node)
    ? `![${node.__alt}](${new RegExp(`^${MEDIA_PATH}$`).test(node.__src) ? node.__src : `<${node.__src}>`})` : null),
  importRegExp: new RegExp(String.raw`!\[([^\]]*)\]\(${MEDIA_PATH}\)`),
  regExp: new RegExp(String.raw`!\[([^\]]*)\]\(${MEDIA_PATH}\)$`),
  replace: (textNode, match) => { textNode.replace($createMediaNode(match[2].replace(/^<|>$/g, ""), match[1])); },
  trigger: ")",
  type: "text-match",
};

const HR: ElementTransformer = {
  dependencies: [HorizontalRuleNode],
  export: (node) => ($isHorizontalRuleNode(node) ? "---" : null),
  regExp: /^(---|\*\*\*|___)\s?$/,
  replace: (parent, _children, _match, isImport) => {
    const line = $createHorizontalRuleNode();
    if (isImport || parent.getNextSibling() != null) parent.replace(line);
    else parent.insertBefore(line);
    line.selectNext();
  },
  type: "element",
};

// GFM tables: the first row is the header; a divider line marks it on the way in.
const TABLE_ROW = /^\|(.+)\|\s?$/;
const TABLE_DIVIDER = /^(\| ?:?-+:? ?)+\|\s?$/;
const TABLE: ElementTransformer = {
  dependencies: [TableNode, TableRowNode, TableCellNode],
  export: (node) => {
    if (!$isTableNode(node)) return null;
    const lines: string[] = [];
    node.getChildren().forEach((row, i) => {
      if (!$isTableRowNode(row)) return;
      const cells = row.getChildren().map((c) => $convertToMarkdownString(MARKDOWN, c as ElementNode).replace(/\n+/g, " ").trim());
      lines.push(`| ${cells.join(" | ")} |`);
      if (i === 0) lines.push(`| ${cells.map(() => "---").join(" | ")} |`);
    });
    return lines.join("\n");
  },
  regExp: TABLE_ROW,
  replace: (parent, _children, match) => {
    const prev = parent.getPreviousSibling();
    if (TABLE_DIVIDER.test(match[0])) {
      if ($isTableNode(prev)) {
        const head = prev.getFirstChild();
        if ($isTableRowNode(head)) head.getChildren().forEach((c) => $isTableCellNode(c) && c.setHeaderStyles(TableCellHeaderStates.ROW));
      }
      parent.remove();
      return;
    }
    const row = $createTableRowNode();
    for (const text of match[1].split("|")) {
      const cell = $createTableCellNode(TableCellHeaderStates.NO_STATUS);
      $convertFromMarkdownString(text.trim(), MARKDOWN, cell);
      row.append(cell);
    }
    if ($isTableNode(prev)) { prev.append(row); parent.remove(); }
    else parent.replace($createTableNode().append(row));
  },
  type: "element",
};
export const MARKDOWN = [HR, TABLE, CHECK_LIST, MEDIA, ...TRANSFORMERS];   // MEDIA before LINK: ![a](b) contains [a](b)

const THEME = {
  code: "md-code",
  table: "md-table",
  tableCell: "md-td",
  tableCellHeader: "md-th",
  list: { checklist: "md-checklist", listitemChecked: "md-check md-checked", listitemUnchecked: "md-check", nested: { listitem: "list-none" } },
  text: { bold: "font-semibold", italic: "italic", strikethrough: "line-through", code: "rounded bg-secondary px-1 font-mono text-[0.9em]" },
};

export default function MdEditor({ value, onChange, placeholder, resolveMedia, upload }: {
  value: string;
  onChange: (markdown: string) => void;
  placeholder?: string;
  resolveMedia?: (path: string) => Promise<string>;   // workspace path → a URL the page can show
  upload?: (file: File) => Promise<string>;           // an added image or video → its workspace path
}) {
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null);
  return (
    <LexicalComposer initialConfig={{
      namespace: "canvas",
      nodes: NODES,
      theme: THEME,
      editorState: () => $convertFromMarkdownString(value, MARKDOWN),
      onError: (e: Error) => { throw e; },
    }}>
      <MediaResolver.Provider value={resolveMedia}>
      <div className="flex h-full flex-col">
        <Toolbar />
        {/* Same margins as the canvas's markdown view, so text doesn't move when editing starts.
            The 28px gutter on the left holds the drag handle (DraggableBlockPlugin's own offsets). */}
        <div className="flex-1 overflow-y-auto py-5 pr-6 sm:pr-8">
          <div ref={setAnchor} className="relative min-h-full pl-7">
            <RichTextPlugin
              contentEditable={<ContentEditable className="prose dark:prose-invert min-h-full focus:outline-none" />}
              placeholder={placeholder ? (
                <div className="pointer-events-none absolute left-7 right-0 top-0 whitespace-pre-line text-sm text-muted-foreground">{placeholder}</div>
              ) : null}
              ErrorBoundary={LexicalErrorBoundary}
            />
          </div>
        </div>
      </div>
      <HistoryPlugin />
      <ListPlugin />
      <LinkPlugin />
      <TablePlugin hasCellMerge={false} hasCellBackgroundColor={false} />
      <HorizontalRulePlugin />
      <Lists />
      <SlashMenu />
      <MediaPlugin upload={upload} />
      {anchor && <DragHandle anchor={anchor} />}
      <MarkdownShortcutPlugin transformers={MARKDOWN} />
      <OnChangePlugin ignoreSelectionChange onChange={(state) => state.read(() => onChange($convertToMarkdownString(MARKDOWN)))} />
      </MediaResolver.Provider>
    </LexicalComposer>
  );
}

// Lexical gives a list one direction, from its first item; each item gets its own here, so an English
// item in an Arabic list runs left to right. And Lexical's checklist click test reads `dir` literally,
// so on these dir="auto" items it never found an Arabic box: the box sits at the item's inline start.
function Lists() {
  const [editor] = useLexicalComposerContext();
  useEffect(() => editor.registerMutationListener(ListItemNode, (mutations) => {
    for (const [key, change] of mutations) if (change !== "destroyed") editor.getElementByKey(key)?.setAttribute("dir", "auto");
  }), [editor]);
  useEffect(() => editor.registerCommand(INSERT_CHECK_LIST_COMMAND, () => { $insertList("check"); return true; }, COMMAND_PRIORITY_LOW), [editor]);
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const li = (e.target as HTMLElement).closest?.('li[role="checkbox"]');
      if (!(li instanceof HTMLElement)) return;
      const r = li.getBoundingClientRect();
      if (getComputedStyle(li).direction === "rtl" ? e.clientX < r.right - 24 : e.clientX > r.left + 24) return;
      e.preventDefault();
      editor.update(() => { const node = $getNearestNodeFromDOMNode(li); if ($isListItemNode(node)) node.toggleChecked(); });
    };
    return editor.registerRootListener((root, prev) => {
      prev?.removeEventListener("click", onClick);
      root?.addEventListener("click", onClick);
    });
  }, [editor]);
  return null;
}

// Images and videos come in from the picker, a paste, or a drop; each uploads, then lands at the caret.
const PICK_MEDIA = createCommand<void>("PICK_MEDIA");
function MediaPlugin({ upload }: { upload?: (file: File) => Promise<string> }) {
  const [editor] = useLexicalComposerContext();
  const input = useRef<HTMLInputElement>(null);
  const add = useCallback(async (files: File[]) => {
    for (const f of files.filter((f) => /^(image|video)\//.test(f.type))) {
      const path = await upload!(f).catch(() => null);
      if (path) editor.update(() => {
        if (!$getSelection()) $getRoot().selectEnd();
        $insertNodes([$createMediaNode(path, f.name.replace(/\.[^.]+$/, ""))]);
      });
    }
  }, [editor, upload]);
  useEffect(() => {
    if (!upload) return;
    const media = (list?: FileList | null) => [...(list ?? [])].filter((f) => /^(image|video)\//.test(f.type));
    return mergeRegister(
      editor.registerCommand(PICK_MEDIA, () => { input.current?.click(); return true; }, COMMAND_PRIORITY_LOW),
      editor.registerCommand(PASTE_COMMAND, (e) => {
        const files = e instanceof ClipboardEvent ? media(e.clipboardData?.files) : [];
        if (!files.length) return false;
        e.preventDefault();
        void add(files);
        return true;
      }, COMMAND_PRIORITY_LOW),
      editor.registerCommand(DROP_COMMAND, (e) => {
        const files = media(e.dataTransfer?.files);
        if (!files.length) return false;
        e.preventDefault();
        void add(files);
        return true;
      }, COMMAND_PRIORITY_LOW),
    );
  }, [editor, upload, add]);
  return upload ? (
    <input ref={input} type="file" accept="image/*,video/*" multiple hidden
           onChange={(e) => { void add([...(e.target.files ?? [])]); e.target.value = ""; }} />
  ) : null;
}

function DragHandle({ anchor }: { anchor: HTMLElement }) {
  const menuRef = useRef<HTMLDivElement>(null);
  const lineRef = useRef<HTMLDivElement>(null);
  return (
    <DraggableBlockPlugin_EXPERIMENTAL
      anchorElem={anchor}
      menuRef={menuRef}
      targetLineRef={lineRef}
      menuComponent={
        <div ref={menuRef} className="md-drag" aria-hidden>
          <svg viewBox="0 0 16 16" className="size-4" fill="currentColor">
            {[4, 8, 12].map((y) => [6, 10].map((x) => <circle key={`${x}${y}`} cx={x} cy={y} r="1.1" />))}
          </svg>
        </div>
      }
      targetLineComponent={<div ref={lineRef} className="md-drop" />}
      isOnMenu={(el) => !!el.closest(".md-drag")}
    />
  );
}

// ---- blocks, shared by the toolbar and the "/" menu ----

const BLOCKS = ["paragraph", "h1", "h2", "h3", "quote", "code"] as const;
const tk = (key: string) => t(`md_${key}` as Parameters<typeof t>[0]);

const $setBlock = (b: string) => {
  const s = $getSelection();
  if ($isRangeSelection(s)) $setBlocksType(s, () =>
    b === "quote" ? $createQuoteNode() : b === "code" ? $createCodeNode() : b === "paragraph" ? $createParagraphNode() : $createHeadingNode(b as HeadingTagType));
};
const insertTable = (editor: LexicalEditor) =>
  editor.dispatchCommand(INSERT_TABLE_COMMAND, { rows: "3", columns: "3", includeHeaders: { rows: true, columns: false } });

class SlashOption extends MenuOption {
  constructor(public glyph: string, public run: (editor: LexicalEditor) => void) { super(glyph); }
}
const SLASH: SlashOption[] = [
  ...BLOCKS.map((b) => new SlashOption(b === "code" ? "codeBlock" : b, () => $setBlock(b))),
  new SlashOption("bullet", (e) => e.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined)),
  new SlashOption("number", (e) => e.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined)),
  new SlashOption("check", (e) => e.dispatchCommand(INSERT_CHECK_LIST_COMMAND, undefined)),
  new SlashOption("table", insertTable),
  new SlashOption("media", (e) => e.dispatchCommand(PICK_MEDIA, undefined)),
  new SlashOption("hr", (e) => e.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined)),
];

function SlashMenu() {
  const [editor] = useLexicalComposerContext();
  const [query, setQuery] = useState<string | null>(null);
  const trigger = useBasicTypeaheadTriggerMatch("/", { minLength: 0 });
  const options = useMemo(() => {
    const q = (query ?? "").toLowerCase();
    return SLASH.filter((o) => !q || tk(o.glyph).toLowerCase().includes(q) || o.glyph.toLowerCase().includes(q));
  }, [query]);
  return (
    <LexicalTypeaheadMenuPlugin<SlashOption>
      onQueryChange={setQuery}
      triggerFn={trigger}
      options={options}
      onSelectOption={(option, node, close) => editor.update(() => { node?.remove(); option.run(editor); close(); })}
      menuRenderFn={(anchorRef, { selectedIndex, selectOptionAndCleanUp, setHighlightedIndex }) =>
        anchorRef.current && options.length ? createPortal(
          <div className="z-50 mt-6 max-h-72 w-56 overflow-y-auto rounded-xl border border-border bg-background p-1 shadow-xl">
            {options.map((o, i) => (
              <button
                key={o.key}
                ref={o.setRefElement}
                onMouseEnter={() => setHighlightedIndex(i)}
                onClick={() => selectOptionAndCleanUp(o)}
                className={cn("flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-start text-sm text-foreground",
                  i === selectedIndex && "bg-secondary")}
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground">{GLYPH[o.glyph]}</span>
                {tk(o.glyph)}
              </button>
            ))}
          </div>,
          anchorRef.current,
        ) : null}
    />
  );
}

// ---- toolbar ----

const FORMATS = ["bold", "italic", "strikethrough", "code"] as const;
const svg = (paths: React.ReactNode) => (
  <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">{paths}</svg>
);
const LINES = <path d="M9 6.5h11M9 12h11M9 17.5h11" />;
const GLYPH: Record<string, React.ReactNode> = {
  undo: svg(<path d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3" />),
  redo: svg(<path d="m15 15 6-6m0 0-6-6m6 6H9a6 6 0 0 0 0 12h3" />),
  bold: <span className="text-[13px] font-bold">B</span>,
  italic: <span className="font-serif text-[14px] italic">I</span>,
  strikethrough: <span className="text-[13px] line-through">S</span>,
  code: svg(<path d="m8 7-5 5 5 5m8-10 5 5-5 5" />),
  link: <Icon name="link" className="size-4" strokeWidth={1.8} />,
  paragraph: <span className="text-[13px] font-medium">T</span>,
  h1: <span className="text-[12px] font-semibold">H1</span>,
  h2: <span className="text-[12px] font-semibold">H2</span>,
  h3: <span className="text-[12px] font-semibold">H3</span>,
  quote: svg(<path d="M7 7h4v4c0 2.5-1.5 4-4 5M14 7h4v4c0 2.5-1.5 4-4 5" />),
  codeBlock: svg(<><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="m10 10-2 2 2 2m4-4 2 2-2 2" /></>),
  bullet: svg(<><circle cx="4.5" cy="6.5" r="1" fill="currentColor" /><circle cx="4.5" cy="12" r="1" fill="currentColor" /><circle cx="4.5" cy="17.5" r="1" fill="currentColor" />{LINES}</>),
  number: svg(<>{LINES}<path d="M4 5v4M3.2 5.5 4 5M3 14.5a1.2 1.2 0 1 1 2 .9L3 19h2.4" strokeWidth={1.4} /></>),
  check: svg(<><rect x="3" y="4" width="6" height="6" rx="1.5" /><path d="m4.6 7 1 1 1.8-2" /><rect x="3" y="14" width="6" height="6" rx="1.5" /><path d="M12 7h9M12 17h9" /></>),
  table: svg(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M3 15h18M9 4v16M15 4v16" /></>),
  media: svg(<><rect x="3" y="4" width="18" height="16" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="m21 16-5-5-8 8" /></>),
  hr: svg(<path d="M3 12h18M8 7h8M8 17h8" strokeOpacity={0.35} />),
  rowAdd: svg(<><rect x="3" y="4" width="18" height="10" rx="2" /><path d="M12 17v4M10 19h4" /></>),
  colAdd: svg(<><rect x="3" y="4" width="11" height="16" rx="2" /><path d="M17 12h4M19 10v4" /></>),
  rowDel: svg(<><rect x="3" y="4" width="18" height="10" rx="2" /><path d="M10 19h4" /></>),
  colDel: svg(<><rect x="3" y="4" width="11" height="16" rx="2" /><path d="M17 12h4" /></>),
};

function Btn({ glyph, pressed, disabled, onClick }: { glyph: string; pressed?: boolean; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      onMouseDown={(e) => e.preventDefault()}   // keep the selection in the editor
      onClick={onClick}
      disabled={disabled}
      title={tk(glyph)}
      aria-label={tk(glyph)}
      aria-pressed={pressed}
      className={cn(
        "flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md transition-colors disabled:cursor-default disabled:opacity-30",
        pressed ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
      )}
    >
      {GLYPH[glyph]}
    </button>
  );
}

const Sep = () => <span className="mx-1 h-4 w-px shrink-0 bg-border" />;

function Toolbar() {
  const [editor] = useLexicalComposerContext();
  const [at, setAt] = useState({ block: "paragraph", formats: [] as string[], list: "", link: false, table: false });
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [url, setUrl] = useState<string | null>(null);   // non-null while typing a link
  const saved = useRef<BaseSelection | null>(null);

  useEffect(() => editor.registerUpdateListener(({ editorState }) => editorState.read(() => {
    const s = $getSelection();
    if (!$isRangeSelection(s)) return;
    const node = s.anchor.getNode();
    const top = node.getTopLevelElement();
    setAt({
      block: $isHeadingNode(top) ? top.getTag() : $isQuoteNode(top) ? "quote" : $isCodeNode(top) ? "code" : "paragraph",
      formats: FORMATS.filter((f) => s.hasFormat(f)),
      list: $isListNode(top) ? top.getListType() : "",
      link: $isLinkNode(node) || $isLinkNode(node.getParent()),
      table: !!$findMatchingParent(node, $isTableCellNode),
    });
  })), [editor]);
  useEffect(() => editor.registerCommand(CAN_UNDO_COMMAND, (v) => { setCanUndo(v); return false; }, COMMAND_PRIORITY_LOW), [editor]);
  useEffect(() => editor.registerCommand(CAN_REDO_COMMAND, (v) => { setCanRedo(v); return false; }, COMMAND_PRIORITY_LOW), [editor]);

  const list = (type: "bullet" | "number" | "check") => editor.dispatchCommand(
    at.list === type ? REMOVE_LIST_COMMAND
      : type === "bullet" ? INSERT_UNORDERED_LIST_COMMAND : type === "number" ? INSERT_ORDERED_LIST_COMMAND : INSERT_CHECK_LIST_COMMAND,
    undefined);
  const startLink = () => {
    if (at.link) return editor.dispatchCommand(TOGGLE_LINK_COMMAND, null);
    saved.current = editor.getEditorState().read(() => $getSelection()?.clone() ?? null);
    setUrl("");
  };
  const applyLink = () => {
    const href = (url ?? "").trim();
    editor.update(() => { if (saved.current) $setSelection(saved.current.clone()); });
    if (href) editor.dispatchCommand(TOGGLE_LINK_COMMAND, /^[a-z][a-z0-9+.-]*:/i.test(href) ? href : `https://${href}`);
    setUrl(null);
  };

  return (
    <div className="flex shrink-0 items-center gap-0.5 overflow-x-auto border-b border-border px-2 py-1.5 [scrollbar-width:none]">
      <Btn glyph="undo" disabled={!canUndo} onClick={() => editor.dispatchCommand(UNDO_COMMAND, undefined)} />
      <Btn glyph="redo" disabled={!canRedo} onClick={() => editor.dispatchCommand(REDO_COMMAND, undefined)} />
      <Sep />
      <select
        value={at.block}
        onChange={(e) => editor.update(() => $setBlock(e.target.value))}
        aria-label={tk("block")}
        className="h-7 shrink-0 cursor-pointer rounded-md bg-transparent px-1.5 text-xs font-medium text-foreground hover:bg-secondary/60 focus:outline-none"
      >
        {BLOCKS.map((b) => <option key={b} value={b}>{tk(b === "code" ? "codeBlock" : b)}</option>)}
      </select>
      <Sep />
      {FORMATS.map((f) => (
        <Btn key={f} glyph={f} pressed={at.formats.includes(f)} onClick={() => editor.dispatchCommand(FORMAT_TEXT_COMMAND, f as TextFormatType)} />
      ))}
      {url === null ? (
        <Btn glyph="link" pressed={at.link} onClick={startLink} />
      ) : (
        <input
          autoFocus
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") applyLink(); if (e.key === "Escape") setUrl(null); }}
          onBlur={() => setUrl(null)}
          placeholder="https://"
          dir="ltr"
          aria-label={tk("link")}
          className="h-7 w-44 shrink-0 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none"
        />
      )}
      <Sep />
      <Btn glyph="bullet" pressed={at.list === "bullet"} onClick={() => list("bullet")} />
      <Btn glyph="number" pressed={at.list === "number"} onClick={() => list("number")} />
      <Btn glyph="check" pressed={at.list === "check"} onClick={() => list("check")} />
      <Sep />
      <Btn glyph="table" onClick={() => insertTable(editor)} />
      <Btn glyph="media" onClick={() => editor.dispatchCommand(PICK_MEDIA, undefined)} />
      <Btn glyph="hr" onClick={() => editor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined)} />
      {at.table && (
        <>
          <Sep />
          <Btn glyph="rowAdd" onClick={() => editor.update(() => { $insertTableRowAtSelection(true); })} />
          <Btn glyph="colAdd" onClick={() => editor.update(() => { $insertTableColumnAtSelection(true); })} />
          <Btn glyph="rowDel" onClick={() => editor.update(() => { $deleteTableRowAtSelection(); })} />
          <Btn glyph="colDel" onClick={() => editor.update(() => { $deleteTableColumnAtSelection(); })} />
        </>
      )}
      <span className="ms-auto hidden shrink-0 ps-3 text-[11px] text-muted-foreground/70 sm:block">{tk("slashHint")}</span>
    </div>
  );
}
