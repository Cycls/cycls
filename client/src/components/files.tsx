import { useState, useEffect, useCallback, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { t, useLang } from "../lib/i18n";
import { LoadingBar } from "./loading-bar";
import { Icon, Spinner } from "./icon";
import { ShareDialog } from "./share-dialog";
import type { FilesPanelProps } from "./chat";

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

// Dropdown menu
export function DropdownMenu({ items, onClose }: {
  items: { label: string; danger?: boolean; onClick: () => void }[];
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute right-0 top-full z-50 mt-1 min-w-[140px] rounded-lg border border-border bg-background shadow-lg py-1">
        {items.map((item) => (
          <button
            key={item.label}
            onClick={(e) => { e.stopPropagation(); item.onClick(); onClose(); }}
            className={`flex w-full items-center px-3 py-1.5 text-sm transition-colors cursor-pointer ${
              item.danger
                ? "text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20"
                : "text-foreground hover:bg-secondary/80"
            }`}
          >
            {item.label}
          </button>
        ))}
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

export function Files({ entries, path, loading, onNavigate, onUpload, onMkdir, onRename, onDelete, onOpenFile, onShareFile, org }: FilesPanelProps) {
  useLang();
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [shareDialog, setShareDialog] = useState<{ path: string; name: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState<string[]>([]);
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  const segments = path ? path.split("/") : [];

  // Resolve thumbnail URLs for image files
  useEffect(() => {
    const images = entries.filter((e) => e.type === "file" && isImage(e.name));
    if (!images.length) { setThumbUrls({}); return; }
    const fullP = (name: string) => path ? `${path}/${name}` : name;
    Promise.all(images.map((e) => onOpenFile(fullP(e.name)).then((url) => [e.name, url] as const)))
      .then((pairs) => setThumbUrls(Object.fromEntries(pairs)));
  }, [entries, path, onOpenFile]);

  const navigate = useCallback((dir: string) => {
    setMenuOpen(null);
    setRenaming(null);
    setCreatingFolder(false);
    onNavigate(dir);
  }, [onNavigate]);

  const fullPath = (name: string) => path ? `${path}/${name}` : name;

  const handleUpload = useCallback(async (files: FileList | File[]) => {
    const names = Array.from(files).map((f) => f.name);
    setUploading((prev) => [...prev, ...names]);
    try {
      await Promise.all(Array.from(files).map((f) => onUpload(path, f)));
    } catch {}
    setUploading((prev) => prev.filter((n) => !names.includes(n)));
    onNavigate(path);
  }, [path, onUpload, onNavigate]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragging(false);
    if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files);
  }, [handleUpload]);

  const sorted = [...entries].sort((a, b) => {
    if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div
      className="flex h-full flex-col"
      onDragEnter={(e) => { e.preventDefault(); dragCounter.current++; setDragging(true); }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={(e) => { e.preventDefault(); dragCounter.current--; if (dragCounter.current <= 0) { dragCounter.current = 0; setDragging(false); } }}
      onDrop={handleDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => { if (e.target.files?.length) { handleUpload(e.target.files); e.target.value = ""; } }}
      />

      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-6">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1 text-sm min-w-0 overflow-hidden">
          <button
            onClick={() => navigate("")}
            className={`shrink-0 transition-colors cursor-pointer ${path ? "text-muted-foreground hover:text-foreground" : "text-foreground font-medium"}`}
          >
            workspace
          </button>
          {segments.map((seg, i) => {
            const segPath = segments.slice(0, i + 1).join("/");
            const isLast = i === segments.length - 1;
            return (
              <span key={segPath} className="flex items-center gap-1 min-w-0">
                <span className="text-muted-foreground/40 shrink-0">/</span>
                <button
                  onClick={() => navigate(segPath)}
                  className={`truncate transition-colors cursor-pointer ${isLast ? "text-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {seg}
                </button>
              </span>
            );
          })}
        </nav>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0 ml-2">
          {[
            { label: t("refresh"),   onClick: () => onNavigate(path),         d: "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" },
            { label: t("newFolder"), onClick: () => setCreatingFolder(true),  d: "M12 10.5v6m3-3H9m4.06-7.19l-2.12-2.12a1.5 1.5 0 00-1.06-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" },
            { label: t("upload"),    onClick: () => fileInputRef.current?.click(), d: "M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" },
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
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto relative">
        {/* Drag overlay */}
        <AnimatePresence>
          {dragging && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
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
            {/* Back row */}
            {path && (
              <button
                onClick={() => navigate(segments.slice(0, -1).join("/"))}
                className="flex w-full items-center gap-3 px-4 py-2.5 sm:px-6 text-sm text-muted-foreground hover:bg-secondary/50 transition-colors cursor-pointer"
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
                  onSubmit={async (name) => {
                    setCreatingFolder(false);
                    await onMkdir(path, name);
                    onNavigate(path);
                  }}
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

              return (
                <div
                  key={entry.name}
                  className="group relative flex items-center gap-3 px-4 py-2.5 sm:px-6 hover:bg-secondary/50 transition-colors cursor-pointer"
                  onClick={() => { if (renaming || menuOpen) return; isDir ? navigate(entryPath) : onOpenFile(entryPath).then((url) => window.open(url, "_blank")); }}
                >
                  {isDir ? (
                    <FolderIcon className="size-5 text-muted-foreground shrink-0" />
                  ) : thumbUrls[entry.name] ? (
                    <img src={thumbUrls[entry.name]} alt={entry.name} className="size-8 rounded object-cover shrink-0" />
                  ) : (
                    <div className="bg-secondary flex size-8 shrink-0 items-center justify-center rounded-lg">
                      <span className="text-[10px] font-medium text-muted-foreground uppercase">
                        {entry.name.split(".").pop()}
                      </span>
                    </div>
                  )}

                  <div className="flex-1 min-w-0">
                    {renaming === entry.name ? (
                      <InlineInput
                        initial={entry.name}
                        onSubmit={async (newName) => {
                          setRenaming(null);
                          if (newName !== entry.name) {
                            await onRename(entryPath, fullPath(newName));
                            onNavigate(path);
                          }
                        }}
                        onCancel={() => setRenaming(null)}
                      />
                    ) : (
                      <span className="text-sm text-foreground truncate block">{entry.name}</span>
                    )}
                  </div>

                  {/* Meta — hidden on mobile to save space, shown on hover */}
                  {!isDir && (
                    <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">
                      {formatSize(entry.size)}
                    </span>
                  )}
                  <span className="hidden sm:block text-xs text-muted-foreground shrink-0 w-16 text-right">
                    {formatDate(entry.modified)}
                  </span>

                  {/* More menu */}
                  <div className="relative shrink-0">
                    <button
                      onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === entry.name ? null : entry.name); }}
                      className="flex size-7 items-center justify-center rounded-md text-muted-foreground sm:opacity-0 sm:group-hover:opacity-100 hover:text-foreground hover:bg-secondary transition-all cursor-pointer"
                      aria-label="Actions"
                    >
                      <svg className="size-4" fill="currentColor" viewBox="0 0 24 24">
                        <circle cx="12" cy="5" r="1.5" />
                        <circle cx="12" cy="12" r="1.5" />
                        <circle cx="12" cy="19" r="1.5" />
                      </svg>
                    </button>
                    {menuOpen === entry.name && (
                      <DropdownMenu
                        onClose={() => setMenuOpen(null)}
                        items={[
                          ...(!isDir ? [{
                            label: t("download"),
                            onClick: () => {
                              onOpenFile(entryPath).then((url) => {
                                const a = document.createElement("a");
                                a.href = url;
                                a.download = entry.name;
                                a.click();
                              });
                            },
                          }] : []),
                          ...(!isDir && onShareFile ? [
                            { label: t("share"), onClick: () => setShareDialog({ path: entryPath, name: entry.name }) },
                          ] : []),
                          {
                            label: t("rename"),
                            onClick: () => setRenaming(entry.name),
                          },
                          {
                            label: t("delete"),
                            danger: true,
                            onClick: async () => {
                              await onDelete(entryPath);
                              onNavigate(path);
                            },
                          },
                        ]}
                      />
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
