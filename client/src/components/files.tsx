import { useState, useEffect, useCallback, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { t, useLang } from "../lib/i18n";
import { LoadingBar } from "./loading-bar";
import { Icon, Spinner } from "./icon";
import { ShareDialog } from "./share-dialog";
import { isRenderable, saveBlob } from "./canvas-utils";
import { useToast } from "../lib/toast";
import type { FilesPanelProps } from "./chat";

const MOVE_TYPE = "application/x-cycls-move";   // internal drag payload (vs OS file drops)

const FolderIcon = ({ className = "size-5" }: { className?: string }) =>
  <Icon name="folder" className={className} strokeWidth={1.5} />;

const IMAGE_EXT = new Set(["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "avif"]);
function isImage(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  return IMAGE_EXT.has(ext);
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

type MenuItem = { label: string; danger?: boolean; onClick: () => void };

// Dropdown menu (anchored under a trigger).
export function DropdownMenu({ items, onClose }: { items: MenuItem[]; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute top-full ltr:right-0 rtl:left-0 z-50 mt-1 min-w-[140px] rounded-lg border border-border bg-background shadow-lg py-1">
        {items.map((item) => (
          <button
            key={item.label}
            onClick={(e) => { e.stopPropagation(); item.onClick(); onClose(); }}
            className={`flex w-full items-center px-3 py-1.5 text-sm transition-colors cursor-pointer ${
              item.danger ? "text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20" : "text-foreground hover:bg-secondary/80"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
    </>
  );
}

// Context menu pinned at cursor coordinates (right-click).
function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-50" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        className="fixed z-50 min-w-[160px] rounded-lg border border-border bg-background shadow-lg py-1"
        style={{ top: Math.min(y, window.innerHeight - 8 - items.length * 34), left: Math.min(x, window.innerWidth - 176) }}
      >
        {items.map((item) => (
          <button
            key={item.label}
            onClick={(e) => { e.stopPropagation(); item.onClick(); onClose(); }}
            className={`flex w-full items-center px-3 py-1.5 text-sm transition-colors cursor-pointer ${
              item.danger ? "text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20" : "text-foreground hover:bg-secondary/80"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
    </>
  );
}

// Destination picker for "Move to…" — touch-friendly (no drag needed).
function MoveDialog({ names, currentDir, listFolders, onMove, onClose }: {
  names: string[];
  currentDir: string;
  listFolders: () => Promise<{ name: string; path: string }[]>;
  onMove: (dest: string) => void;
  onClose: () => void;
}) {
  const [folders, setFolders] = useState<{ name: string; path: string }[] | null>(null);
  const [q, setQ] = useState("");
  useEffect(() => { listFolders().then(setFolders); }, [listFolders]);

  // Can't move into where they already are, into themselves, or a descendant.
  const moved = names.map((n) => (currentDir ? `${currentDir}/${n}` : n));
  const blocked = (dest: string) => dest === currentDir || moved.some((m) => dest === m || dest.startsWith(`${m}/`));
  const list = [{ name: "", path: "" }, ...(folders || [])]
    .filter((f) => !blocked(f.path) && f.path.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-[60] flex max-h-[70vh] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-background shadow-xl" dir="ltr">
        <div className="border-b border-border px-4 py-3 text-sm font-medium text-foreground">
          {t("moveTo")} <span className="text-muted-foreground">({names.length})</span>
        </div>
        <div className="border-b border-border p-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("sortName")}
            className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {folders === null ? (
            <LoadingBar />
          ) : list.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">—</div>
          ) : list.map((f) => (
            <button
              key={f.path || "/"}
              onClick={() => onMove(f.path)}
              className="flex w-full items-center gap-2 px-4 py-2 text-sm text-foreground hover:bg-secondary/80 cursor-pointer"
            >
              <FolderIcon className="size-4 text-muted-foreground shrink-0" />
              <span className="truncate">{f.path || t("workspace")}</span>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

// Rename / New folder inline dialog. Exported for reuse in ChatsPanel.
export function InlineInput({ initial, onSubmit, onCancel }: {
  initial: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSubmit(value.trim()); }}
      className="flex items-center gap-2"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
        onBlur={onCancel}
        className="h-7 rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent w-48"
      />
      <button
        type="submit"
        className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer shrink-0"
        onMouseDown={(e) => e.preventDefault()}
      >
        Save
      </button>
    </form>
  );
}

type SortKey = "name" | "size" | "modified" | "type";

const fileExt = (name: string) => (name.includes(".") ? name.split(".").pop()!.toLowerCase() : "");

export function Files({ entries, path, loading, onNavigate, onUpload, onMkdir, onRename, onDelete, onOpenFile, onShareFile, onOpenInCanvas, listFolders, maxUpload, org }: FilesPanelProps) {
  useLang();
  const { error: toastError } = useToast();
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [ctx, setCtx] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null);
  const [moveDialog, setMoveDialog] = useState<{ names: string[] } | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [shareDialog, setShareDialog] = useState<{ path: string; name: string } | null>(null);
  const [dragging, setDragging] = useState(false);           // OS file drag → upload overlay
  const [dropDir, setDropDir] = useState<string | null>(null); // folder/crumb under an internal move
  const [uploading, setUploading] = useState<string[]>([]);
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchor, setAnchor] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);
  const [sortMenu, setSortMenu] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [uploadMenu, setUploadMenu] = useState(false);
  const dragCounter = useRef(0);

  const segments = path ? path.split("/") : [];
  const fullPath = useCallback((name: string) => (path ? `${path}/${name}` : name), [path]);

  // Reset transient state when the directory changes.
  useEffect(() => { setSelected(new Set()); setAnchor(null); setMenuOpen(null); }, [path]);

  // Resolve thumbnail URLs for image files
  useEffect(() => {
    const images = entries.filter((e) => e.type === "file" && isImage(e.name));
    if (!images.length) { setThumbUrls({}); return; }
    const fp = (name: string) => (path ? `${path}/${name}` : name);
    Promise.all(images.map((e) => onOpenFile(fp(e.name)).then((url) => [e.name, url] as const)))
      .then((pairs) => setThumbUrls(Object.fromEntries(pairs)));
  }, [entries, path, onOpenFile]);

  const navigate = useCallback((dir: string) => {
    setMenuOpen(null);
    setRenaming(null);
    setCreatingFolder(false);
    onNavigate(dir);
  }, [onNavigate]);

  const handleUpload = useCallback(async (files: FileList | File[], dir = path) => {
    const maxMb = maxUpload ?? 512;
    const all = Array.from(files);
    const list = all.filter((f) => f.size <= maxMb * 1024 * 1024);
    const skipped = all.length - list.length;
    if (skipped) toastError(`${skipped === 1 ? "File" : `${skipped} files`} over the ${maxMb} MB limit ${skipped === 1 ? "was" : "were"} skipped.`);
    if (!list.length) return;
    // Folder uploads carry webkitRelativePath (e.g. "folder/sub/a.txt"); preserve
    // the structure by uploading each file into its sub-directory.
    const relOf = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
    const names = list.map(relOf);
    setUploading((prev) => [...prev, ...names]);
    const uploadOne = async (f: File) => {
      const rel = relOf(f);
      const sub = rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "";
      try { await onUpload([dir, sub].filter(Boolean).join("/"), f); } catch {}
    };
    // Cap concurrency so a large folder doesn't fan out into hundreds of requests.
    let i = 0;
    await Promise.all(Array.from({ length: Math.min(4, list.length) }, async () => {
      while (i < list.length) await uploadOne(list[i++]);
    }));
    setUploading((prev) => prev.filter((n) => !names.includes(n)));
    onNavigate(path);
  }, [path, onUpload, onNavigate, maxUpload, toastError]);

  // Move selected entries (or a single one) into destDir.
  const moveInto = useCallback(async (names: string[], destDir: string) => {
    const moves = names.filter((n) => {
      const src = path ? `${path}/${n}` : n;
      const dest = destDir ? `${destDir}/${n}` : n;
      return src !== dest && src !== destDir;   // skip no-op and folder-into-itself
    });
    if (!moves.length) return;
    for (const n of moves) {
      try { await onRename(path ? `${path}/${n}` : n, destDir ? `${destDir}/${n}` : n); } catch {}
    }
    setSelected(new Set());
    onNavigate(path);
  }, [path, onRename, onNavigate]);

  // ---- selection ----
  const sorted = [...entries].sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;   // folders first
    let cmp = 0;
    if (sortKey === "name") cmp = a.name.localeCompare(b.name);
    else if (sortKey === "size") cmp = a.size - b.size;
    else if (sortKey === "type") cmp = fileExt(a.name).localeCompare(fileExt(b.name)) || a.name.localeCompare(b.name);
    else cmp = new Date(a.modified).getTime() - new Date(b.modified).getTime();
    return sortAsc ? cmp : -cmp;
  });

  const selectRow = (e: React.MouseEvent, name: string) => {
    if (e.metaKey || e.ctrlKey) {
      setSelected((p) => { const n = new Set(p); n.has(name) ? n.delete(name) : n.add(name); return n; });
      setAnchor(name);
    } else if (e.shiftKey && anchor) {
      const names = sorted.map((s) => s.name);
      const i1 = names.indexOf(anchor), i2 = names.indexOf(name);
      if (i1 >= 0 && i2 >= 0) {
        const [lo, hi] = [Math.min(i1, i2), Math.max(i1, i2)];
        setSelected(new Set(names.slice(lo, hi + 1)));
      }
    } else {
      setSelected(new Set([name]));
      setAnchor(name);
    }
  };

  const toggleSelect = (name: string) => {
    setSelected((p) => { const n = new Set(p); n.has(name) ? n.delete(name) : n.add(name); return n; });
    setAnchor(name);
  };

  const open = (name: string, isDir: boolean) => {
    const ep = fullPath(name);
    if (isDir) return navigate(ep);
    if (isRenderable(name) && onOpenInCanvas) return onOpenInCanvas(ep, name);
    onOpenFile(ep).then((url) => saveBlob(url, name));
  };

  const deleteNames = useCallback(async (names: string[]) => {
    for (const n of names) { try { await onDelete(fullPath(n)); } catch {} }
    setSelected(new Set());
    onNavigate(path);
  }, [fullPath, onDelete, onNavigate, path]);

  // Delete / Escape on the selection (ignore while typing in an input).
  useEffect(() => {
    if (!selected.size) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (e.key === "Escape") setSelected(new Set());
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteNames([...selected]); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, deleteNames]);

  // Per-row menu (⋯ and right-click): a Select toggle + single-row actions.
  // Bulk actions live in the selection bar. The Select item is the phone-
  // friendly way to multi-select (no modifier keys needed).
  const itemsFor = (name: string, isDir: boolean): MenuItem[] => {
    const ep = fullPath(name);
    return [
      { label: selected.has(name) ? t("deselect") : t("select"), onClick: () => toggleSelect(name) },
      { label: t("download"), onClick: () => onOpenFile(ep).then((u) => saveBlob(u, isDir ? `${name}.zip` : name)) },
      ...(!isDir && onShareFile ? [{ label: t("share"), onClick: () => setShareDialog({ path: ep, name }) }] : []),
      { label: t("moveTo"), onClick: () => setMoveDialog({ names: selected.has(name) ? [...selected] : [name] }) },
      { label: t("rename"), onClick: () => setRenaming(name) },
      { label: t("delete"), danger: true, onClick: () => deleteNames([name]) },
    ];
  };

  // Download a file (or a folder as <name>.zip).
  const downloadEntry = (name: string, isDir: boolean) =>
    onOpenFile(fullPath(name)).then((u) => saveBlob(u, isDir ? `${name}.zip` : name)).catch(() => {});

  // ---- OS file drag (upload) on the whole panel ----
  const isFileDrag = (e: React.DragEvent) => e.dataTransfer.types.includes("Files");
  const isMoveDrag = (e: React.DragEvent) => e.dataTransfer.types.includes(MOVE_TYPE);

  return (
    <div
      className="flex flex-1 min-h-0 flex-col"
      onDragEnter={(e) => { if (!isFileDrag(e)) return; e.preventDefault(); dragCounter.current++; setDragging(true); }}
      onDragOver={(e) => { if (isFileDrag(e)) e.preventDefault(); }}
      onDragLeave={(e) => { if (!isFileDrag(e)) return; e.preventDefault(); dragCounter.current--; if (dragCounter.current <= 0) { dragCounter.current = 0; setDragging(false); } }}
      onDrop={(e) => { if (!isFileDrag(e)) return; e.preventDefault(); dragCounter.current = 0; setDragging(false); if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files); }}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => { if (e.target.files?.length) { handleUpload(e.target.files); e.target.value = ""; } }}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        className="hidden"
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => { if (e.target.files?.length) { handleUpload(e.target.files); e.target.value = ""; } }}
      />

      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-6">
        {/* Breadcrumb — crumbs are move drop-targets */}
        <nav className="flex items-center gap-1 text-sm min-w-0 overflow-hidden">
          <button
            onClick={() => navigate("")}
            onDragOver={(e) => { if (isMoveDrag(e)) { e.preventDefault(); setDropDir(""); } }}
            onDragLeave={() => setDropDir((d) => (d === "" ? null : d))}
            onDrop={(e) => { if (!isMoveDrag(e)) return; e.preventDefault(); setDropDir(null); moveInto(JSON.parse(e.dataTransfer.getData(MOVE_TYPE)), ""); }}
            className={`shrink-0 rounded px-1 transition-colors cursor-pointer ${dropDir === "" ? "bg-accent/20 text-foreground" : path ? "text-muted-foreground hover:text-foreground" : "text-foreground font-medium"}`}
          >
            {t("workspace")}
          </button>
          {segments.map((seg, i) => {
            const segPath = segments.slice(0, i + 1).join("/");
            const isLast = i === segments.length - 1;
            return (
              <span key={segPath} className="flex items-center gap-1 min-w-0">
                <span className="text-muted-foreground/40 shrink-0">/</span>
                <button
                  onClick={() => navigate(segPath)}
                  onDragOver={(e) => { if (isMoveDrag(e)) { e.preventDefault(); setDropDir(segPath); } }}
                  onDragLeave={() => setDropDir((d) => (d === segPath ? null : d))}
                  onDrop={(e) => { if (!isMoveDrag(e)) return; e.preventDefault(); setDropDir(null); moveInto(JSON.parse(e.dataTransfer.getData(MOVE_TYPE)), segPath); }}
                  className={`truncate rounded px-1 transition-colors cursor-pointer ${dropDir === segPath ? "bg-accent/20 text-foreground" : isLast ? "text-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {seg}
                </button>
              </span>
            );
          })}
        </nav>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0 ml-2">
          {/* Sort */}
          <div className="relative">
            <button
              onClick={() => setSortMenu((o) => !o)}
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              aria-label={t("sortBy")} title={t("sortBy")}
            >
              <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 7h12M3 12h9M3 17h6m6 0l3 3 3-3m-3 3V8" />
              </svg>
            </button>
            {sortMenu && (
              <DropdownMenu
                onClose={() => setSortMenu(false)}
                items={([["name", t("sortName")], ["type", t("sortType")], ["modified", t("sortDate")], ["size", t("sortSize")]] as [SortKey, string][]).map(([k, label]) => ({
                  label: `${sortKey === k ? (sortAsc ? "↑ " : "↓ ") : ""}${label}`,
                  onClick: () => { if (sortKey === k) setSortAsc((v) => !v); else { setSortKey(k); setSortAsc(true); } },
                }))}
              />
            )}
          </div>
          {[
            { label: t("refresh"),   onClick: () => onNavigate(path),         d: "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" },
            { label: t("newFolder"), onClick: () => setCreatingFolder(true),  d: "M12 10.5v6m3-3H9m4.06-7.19l-2.12-2.12a1.5 1.5 0 00-1.06-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" },
          ].map((b) => (
            <button
              key={b.label}
              onClick={b.onClick}
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              aria-label={b.label}
              title={b.label}
            >
              <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d={b.d} />
              </svg>
            </button>
          ))}
          {/* Upload (file or folder) */}
          <div className="relative">
            <button
              onClick={() => setUploadMenu((o) => !o)}
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
              aria-label={t("upload")} title={t("upload")}
            >
              <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
            </button>
            {uploadMenu && (
              <DropdownMenu
                onClose={() => setUploadMenu(false)}
                items={[
                  { label: t("uploadFile"), onClick: () => fileInputRef.current?.click() },
                  { label: t("uploadFolder"), onClick: () => folderInputRef.current?.click() },
                ]}
              />
            )}
          </div>
        </div>
      </div>

      {/* Selection bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 border-b border-border bg-secondary/30 px-4 py-1.5 sm:px-6 text-xs">
          <span className="text-foreground font-medium">{selected.size} {t("selected")}</span>
          <div className="flex-1" />
          <button
            onClick={() => [...selected].forEach((n) => { const e = entries.find((x) => x.name === n); if (e) downloadEntry(n, e.type === "directory"); })}
            className="text-muted-foreground hover:text-foreground cursor-pointer"
          >
            {t("download")}
          </button>
          <button onClick={() => setMoveDialog({ names: [...selected] })} className="text-muted-foreground hover:text-foreground cursor-pointer">{t("moveTo")}</button>
          <button onClick={() => deleteNames([...selected])} className="text-red-500 hover:underline cursor-pointer">{t("delete")}</button>
          <button onClick={() => setSelected(new Set())} className="text-muted-foreground hover:text-foreground cursor-pointer">✕</button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto relative">
        {/* OS-file drag overlay */}
        <AnimatePresence>
          {dragging && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}
              className="absolute inset-0 z-30 flex items-center justify-center bg-background/80 border-2 border-dashed border-accent/40 rounded-lg m-2"
            >
              <div className="text-center">
                <Icon name="upload" className="size-8 mx-auto mb-2 text-muted-foreground" strokeWidth={1.5} />
                <p className="text-sm text-muted-foreground">Drop files to upload</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <LoadingBar active={loading && entries.length > 0} />

        {loading && entries.length === 0 ? (
          <LoadingBar />
        ) : (
          <div className="divide-y divide-border">
            {/* Back row — move drop-target */}
            {path && (
              <button
                onClick={() => navigate(segments.slice(0, -1).join("/"))}
                onDragOver={(e) => { if (isMoveDrag(e)) { e.preventDefault(); setDropDir("//up"); } }}
                onDragLeave={() => setDropDir((d) => (d === "//up" ? null : d))}
                onDrop={(e) => { if (!isMoveDrag(e)) return; e.preventDefault(); setDropDir(null); moveInto(JSON.parse(e.dataTransfer.getData(MOVE_TYPE)), segments.slice(0, -1).join("/")); }}
                className={`flex w-full items-center gap-3 px-4 py-2.5 sm:px-6 text-sm text-muted-foreground transition-colors cursor-pointer ${dropDir === "//up" ? "bg-accent/20" : "hover:bg-secondary/50"}`}
              >
                <Icon name="chevron-left" className="size-4 shrink-0" />
                <span>..</span>
              </button>
            )}

            {/* New folder input */}
            {creatingFolder && (
              <div className="flex items-center gap-3 px-4 py-2.5 sm:px-6">
                <FolderIcon className="size-5 text-muted-foreground shrink-0" />
                <InlineInput
                  initial=""
                  onSubmit={async (name) => { setCreatingFolder(false); await onMkdir(path, name); onNavigate(path); }}
                  onCancel={() => setCreatingFolder(false)}
                />
              </div>
            )}

            {/* Uploading indicators */}
            {uploading.map((name) => (
              <div key={name} className="flex items-center gap-3 px-4 py-2.5 sm:px-6 opacity-50">
                <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg">
                  <span className="text-[10px] font-medium text-muted-foreground uppercase">{name.split(".").pop()}</span>
                </div>
                <span className="text-sm text-foreground truncate flex-1">{name}</span>
                <Spinner className="size-4 text-muted-foreground shrink-0" />
              </div>
            ))}

            {/* File list */}
            {sorted.map((entry) => {
              const entryPath = fullPath(entry.name);
              const isDir = entry.type === "directory";
              const isSel = selected.has(entry.name);
              const isDropTarget = isDir && dropDir === entryPath;

              return (
                <div
                  key={entry.name}
                  draggable={renaming !== entry.name}
                  onDragStart={(e) => {
                    const names = isSel ? [...selected] : [entry.name];
                    if (!isSel) { setSelected(new Set([entry.name])); }
                    e.dataTransfer.setData(MOVE_TYPE, JSON.stringify(names));
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  // Folders accept moves and OS-file drops.
                  onDragOver={isDir ? (e) => { if (isMoveDrag(e) || isFileDrag(e)) { e.preventDefault(); e.stopPropagation(); setDropDir(entryPath); } } : undefined}
                  onDragLeave={isDir ? () => setDropDir((d) => (d === entryPath ? null : d)) : undefined}
                  onDrop={isDir ? (e) => {
                    if (isMoveDrag(e)) { e.preventDefault(); e.stopPropagation(); setDropDir(null); moveInto(JSON.parse(e.dataTransfer.getData(MOVE_TYPE)), entryPath); }
                    else if (isFileDrag(e) && e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); setDropDir(null); setDragging(false); dragCounter.current = 0; handleUpload(e.dataTransfer.files, entryPath); }
                  } : undefined}
                  onClick={(e) => {
                    if (renaming) return;
                    // Modifier-click always selects (desktop). Once a selection
                    // exists we're in "select mode" → a tap toggles instead of
                    // opening. With nothing selected, a plain tap opens (the only
                    // thing that works well on touch).
                    if (e.metaKey || e.ctrlKey || e.shiftKey) selectRow(e, entry.name);
                    else if (selected.size > 0) toggleSelect(entry.name);
                    else open(entry.name, isDir);
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setCtx({ x: e.clientX, y: e.clientY, items: itemsFor(entry.name, isDir) });
                  }}
                  className={`group relative flex items-center gap-3 px-4 py-2.5 sm:px-6 transition-colors cursor-pointer ${
                    isDropTarget ? "bg-accent/20 ring-1 ring-accent/40 ring-inset" : isSel ? "bg-secondary" : "hover:bg-secondary/50"
                  }`}
                >
                  {isDir ? (
                    <FolderIcon className="size-5 text-muted-foreground shrink-0" />
                  ) : thumbUrls[entry.name] ? (
                    <img src={thumbUrls[entry.name]} alt={entry.name} className="size-8 rounded object-cover shrink-0" draggable={false} />
                  ) : (
                    <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg">
                      <span className="text-[10px] font-medium text-muted-foreground uppercase">{entry.name.split(".").pop()}</span>
                    </div>
                  )}

                  <div className="flex-1 min-w-0">
                    {renaming === entry.name ? (
                      <InlineInput
                        initial={entry.name}
                        onSubmit={async (newName) => {
                          setRenaming(null);
                          if (newName !== entry.name) { await onRename(entryPath, fullPath(newName)); onNavigate(path); }
                        }}
                        onCancel={() => setRenaming(null)}
                      />
                    ) : (
                      <span className="text-sm text-foreground truncate block select-none">{entry.name}</span>
                    )}
                  </div>

                  {/* Meta */}
                  {!isDir && (
                    <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">{formatSize(entry.size)}</span>
                  )}
                  <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">{formatDate(entry.modified)}</span>

                  {/* More menu */}
                  <div className="relative shrink-0">
                    <button
                      onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === entry.name ? null : entry.name); }}
                      className="flex size-7 items-center justify-center rounded-md text-muted-foreground sm:opacity-0 sm:group-hover:opacity-100 hover:text-foreground hover:bg-secondary transition-all cursor-pointer"
                      aria-label="Actions"
                    >
                      <svg className="size-4" fill="currentColor" viewBox="0 0 24 24">
                        <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                      </svg>
                    </button>
                    {menuOpen === entry.name && (
                      <DropdownMenu onClose={() => setMenuOpen(null)} items={itemsFor(entry.name, isDir)} />
                    )}
                  </div>
                </div>
              );
            })}

            {/* Empty state */}
            {sorted.length === 0 && !creatingFolder && uploading.length === 0 && (
              <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
                <FolderIcon className="size-10 mb-3 opacity-30" />
                <p className="text-sm">{t("noFiles")}</p>
                <p className="text-xs mt-1">{t("noFilesSub")}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {ctx && <ContextMenu x={ctx.x} y={ctx.y} items={ctx.items} onClose={() => setCtx(null)} />}

      {moveDialog && (
        <MoveDialog
          names={moveDialog.names}
          currentDir={path}
          listFolders={listFolders}
          onMove={(dest) => { moveInto(moveDialog.names, dest); setMoveDialog(null); }}
          onClose={() => setMoveDialog(null)}
        />
      )}

      {shareDialog && onShareFile && (
        <ShareDialog
          onClose={() => setShareDialog(null)}
          mode="file"
          subtitle={shareDialog.name}
          org={org}
          onShare={(audience) => onShareFile(shareDialog.path, audience)}
        />
      )}
    </div>
  );
}
