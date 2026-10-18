import { useState, useEffect, useRef, useMemo, useCallback, lazy, Suspense } from "react";
import type { VideoEditorApi, WriteFile } from "../hooks/use-files";
import { useEscape } from "../hooks/use-escape";
import { track } from "../lib/analytics";
import { createPortal } from "react-dom";
import { motion, AnimatePresence, Reorder } from "framer-motion";
import { Icon } from "./icon";
import { AppIcon } from "./app-icon";
import { LoadingBar } from "./loading-bar";
import { DropdownMenu } from "./files";
import { ShareDialog } from "./share-dialog";
import { TextPart } from "./parts/text-part";
import { HighlightedCode } from "./parts/code-part";
import { isHtml, isMd, isPdf, isImage, isAudio, isVideo, isSpreadsheet, isDocx, isPresentation, isOffice, isDesignEditor, isDeck, isComposition, is3d, codeLang, extTint, tintTile, tintLabel, tileExt, saveBlob, DESIGN_PRESETS } from "./canvas-utils";
import { SpreadsheetView } from "./spreadsheet-view";
import { DocxView } from "./docx-view";
import { SlidesView } from "./slides-view";
import { DesignPresenceRow } from "./design-presence";
import { VideoEditorView, canEditVideo, flushVideoEditor, videoEditorOpen, watchVideoEditors } from "./video-editor-view";
import { DesignEditorView, canFullscreen, designEditorComments, designPage, flushDesignEditor, fullscreenDesignEditor, showDesignPage, useDesignPages, type DesignHost } from "./design-editor-view";
import { VersionHistory } from "./version-history";
import { CommentButtons, CommentLayer, CommentsList } from "./comments";
import { DeckView, EditPreviewSwitch, PageTabs, parseDeck, type DeckOp } from "./deck-view";
import type { ShareLinks } from "./share-dialog";
import type { PollApi } from "../lib/polls";
import { attachBridge, appScope } from "./app-bridge";
import { injectShim } from "./app-shim";
import { SaveDialog } from "./save-dialog";
import type { AppInfo } from "../hooks/use-apps";
import { usePaneWidth } from "../hooks/use-pane-width";
import { slide, cn } from "../lib/utils";
import { t, getLang } from "../lib/i18n";

// Renderer choice comes from the PATH, never the display name: an app's tab
// is titled by its manifest ("Sales Portfolio"), which has no extension, and
// every type check would fall through to the unsupported-file card.
export const fileKind = (file: { path: string; name: string }) => file.path || file.name;

const MdEditor = lazy(() => import("./md-editor"));
const CompositionView = lazy(() => import("./composition-view"));
// A document's image paths are relative to its folder, as markdown means them; agents sometimes
// write them from the workspace root, so that is the fallback. Silent: a miss beside it is normal.
export const mediaResolver = (docPath: string, openFile: (path: string, silent?: boolean) => Promise<string>) => {
  const folder = docPath.slice(0, docPath.lastIndexOf("/") + 1);
  return (p: string) => (folder ? openFile(folder + p, true).catch(() => openFile(p, true)) : openFile(p, true));
};
// Markdown the rich editor can't carry through a save — math, HTML, footnotes — edits as plain text.
export const PLAIN_MD = /\$\$|\\\(|\\\[|\$[^$\n]+\$|<\/?[a-z][a-z0-9-]*(\s[^>]*)?>|\[\^[^\]]+\]/im;

export interface CanvasFile {
  path: string;
  name: string;
  // Apps carry their manifest identity; files fall back to the ext tint dot.
  icon?: string;      // emoji
  iconSrc?: string;   // image (data: or blob:)
  letter?: string;    // first letter of the app name
  writable?: boolean; // a document written here (the instructions): missing opens empty, Edit sits in the header
}

// Fetch a file's content for the canvas. pdf → blob URL (native viewer);
// other types → source text. Revokes the blob URL on change/unmount. Pass
// file=null to fetch nothing (e.g. unrenderable file shown as a download card).
export function useFileContent(
  file: CanvasFile | null,
  readFile: (p: string, silent?: boolean) => Promise<string>,
  openFile: (p: string, silent?: boolean) => Promise<string>,
  reloadKey: number = 0,   // bump to re-fetch: the agent rewrote the file
  designAsPictures: boolean = false,   // no .fig editor (a shared page): fetch its slide manifest
) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const shown = useRef<string | null>(null);
  const loaded = useRef(false);   // this file has shown content — a failed refetch keeps it

  useEffect(() => {
    if (!file) { setContent(null); setError(false); shown.current = null; return; }
    const fresh = shown.current !== file.path;
    shown.current = file.path;
    let cancelled = false;
    let blobUrl: string | null = null;
    // Only blank for a DIFFERENT file. A refetch used to unmount the document — so every
    // agent turn destroyed an open app, taking its scroll, its form state and any write
    // still inside the shim's debounce. Unchanged content now re-renders to the same
    // srcDoc and the frame is never touched.
    if (fresh) { setContent(null); setError(false); loaded.current = false; }
    // Only formats we render from source fetch as text. Everything else — pdf,
    // media, spreadsheets — fetches bytes, so a binary is never handed to a
    // text renderer. Office docs fetch the server's on-demand PDF render of
    // themselves (?as=pdf) and ride the PDF viewer.
    const kind = fileKind(file);
    // Office ?as=pdf / ?as=slides is fetched silently — if the converter is down
    // it throws, we set error, and CanvasDoc shows the download card (no toast).
    // Presentations fetch the slide manifest as text; .docx and spreadsheets
    // fetch their raw bytes (a blob URL) for the native renderer; other office
    // files fetch the server's PDF render.
    // Decks and editor-less designs fetch their slide manifest; a Video composition the page the
    // video service builds of it (always a JSON answer).
    const load = isDeck(kind) || (designAsPictures && isDesignEditor(kind))
      ? readFile(`${file.path}?as=slides`, true)
      : isComposition(kind)
      ? readFile(`${file.path}?as=player`, true)
      : isMd(kind) || isHtml(kind) || codeLang(kind) != null
      ? readFile(file.path, file.writable)
      : isPresentation(kind)
      ? readFile(`${file.path}?as=slides`, true)
      : (isOffice(kind) ? openFile(`${file.path}?as=pdf`, true) : openFile(file.path))
          .then((url) => { blobUrl = url; return url; });
    // A success clears an earlier failure; a failed refetch keeps what's shown.
    load.then((v) => { if (!cancelled) { setContent(v); setError(false); loaded.current = true; } })
        .catch((e) => { if (!cancelled) { if (file.writable && e?.status === 404) setContent(""); else if (!loaded.current) setError(true); } });
    return () => { cancelled = true; if (blobUrl) URL.revokeObjectURL(blobUrl); };
  }, [file?.path, file?.name, file?.writable, readFile, openFile, reloadKey, designAsPictures]);

  return { content, setContent, error };
}

// Read-only body — renders a loaded file by type. `shared` tightens the html
// sandbox (drop allow-popups) for content that's untrusted to the viewer.
interface PendingSave {
  name: string;
  content: string;
  resolve: (path: string | null) => void;
}

// Without readFile (shared pages have no workspace) this is a plain sandboxed doc.
function HtmlDoc({ file, content, shared, readFile, writeFile, listFolders, fetchConnector, appData }: {
  file: CanvasFile;
  content: string;
  shared: boolean;
  readFile?: (path: string, silent?: boolean) => Promise<string>;
  writeFile?: WriteFile;
  listFolders?: () => Promise<{ name: string; path: string }[]>;
  fetchConnector?: (name: string, path: string, init: { method: string; headers: Record<string, string>; body?: string }) => Promise<{ status: number; body: string; contentType: string }>;
  appData?: (slug: string, op: Record<string, unknown>) => Promise<unknown>;
}) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [pending, setPending] = useState<PendingSave | null>(null);
  const [crash, setCrash] = useState<string | null>(null);
  // Only an app gets workspace access; every other html is just a document.
  const isApp = appScope(file.path) !== null;
  const canSave = isApp && !shared && !!writeFile && !!listFolders;
  // A shared view has no workspace, but it still needs the shim: without it the app has no
  // localStorage polyfill and white-screens on the first library that touches storage. So it
  // gets a bridge that answers, and refuses.
  const readForApp = readFile ?? (shared
    ? () => Promise.reject(new Error("not available in a shared view"))
    : undefined);

  useEffect(() => {
    if (!ref.current || !readForApp || !isApp) return;
    setCrash(null);
    return attachBridge({
      frame: ref.current,
      appPath: file.path,
      onError: setCrash,
      // Silent: the app is told what failed over the bridge and decides what it
      // means. A missing key-value file on first open is not a host-level error.
      readFile: (p) => readForApp(p, true),
      writeFile: shared || !writeFile ? undefined : async (p, text) => { await writeFile(p, text, true); },
      // One dialog per save: the app never holds standing permission to write
      // outside its own folder.
      requestSave: canSave
        ? (name, body) => new Promise<string | null>((resolve) =>
            setPending({ name, content: body, resolve }))
        : undefined,
      fetchConnector: shared ? undefined : fetchConnector,
      appData: shared ? undefined : appData,
      context: {
        // Dark mode lives on document.body (lib/utils applyTheme), not <html>.
        theme: document.body.classList.contains("dark") ? "dark" : "light",
        locale: document.documentElement.lang || "en",
      },
    });
  }, [file.path, readForApp, writeFile, shared, canSave, isApp, appData]);

  const doc = useMemo(() => (readForApp && isApp ? injectShim(content) : content), [content, readForApp, isApp]);

  const settle = async (path: string | null) => {
    if (!pending) return;
    const { content: body, resolve } = pending;
    setPending(null);
    if (!path) return resolve(null);
    try {
      await writeFile!(path, body);
      resolve(path);
    } catch {
      resolve(null);
    }
  };

  return (
    <div className="relative h-full w-full">
      <iframe
        ref={ref}
        sandbox={shared ? "allow-scripts" : "allow-scripts allow-popups"}
        srcDoc={doc}
        title={file.name}
        className="h-full w-full border-0 bg-white"
      />
      {crash && (
        <div className="absolute inset-x-0 bottom-0 border-t border-border bg-card px-4 py-2 text-xs text-destructive">
          {t("appCrashed")}: {crash}
        </div>
      )}
      {pending && listFolders && (
        <SaveDialog
          name={pending.name}
          bytes={new Blob([pending.content]).size}
          listFolders={listFolders}
          onConfirm={(path) => void settle(path)}
          onCancel={() => void settle(null)}
        />
      )}
    </div>
  );
}

// Extension tile + download/share — shown for a file with no in-browser
// renderer, and when an Office file's PDF conversion is unavailable.
function NoPreviewCard({ file, onDownload, onShare }: {
  file: CanvasFile;
  onDownload?: () => void;
  onShare?: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex size-16 items-center justify-center rounded-2xl bg-secondary text-xs font-bold text-muted-foreground" style={tintTile(fileKind(file))}>
        <span style={tintLabel(fileKind(file))}>{(tileExt(fileKind(file)) || "file").slice(0, 4).toUpperCase()}</span>
      </div>
      <p className="text-sm font-medium text-foreground">{file.name}</p>
      <p className="text-xs text-muted-foreground">{t("noPreview")}</p>
      {(onDownload || onShare) && (
        <div className="mt-1 flex gap-2">
          {onDownload && (
            <button onClick={onDownload} className="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity cursor-pointer">
              {t("download")}
            </button>
          )}
          {onShare && (
            <button onClick={onShare} className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary/80 transition-colors cursor-pointer">
              {t("share")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const pageQuery = (page?: string) => (page ? `&page=${encodeURIComponent(page)}` : "");

// A design without its editor (a preview, a shared page), one page at a time.
function DesignPages({ file, data, readFile, openFile, downloads, tabs = true, onPage, onReload, onSlideOp }: {
  file: CanvasFile;
  data: string;
  tabs?: boolean;                      // its own page tabs (false: the canvas shows them above)
  readFile?: (path: string, silent?: boolean) => Promise<string>;   // fetches another page (none: the one given)
  openFile?: (path: string, silent?: boolean) => Promise<string>;
  downloads?: boolean;                 // the picture's own Download buttons (where no menu has them)
  onPage?: (page: string) => void;
  onReload?: () => void;
  onSlideOp?: (op: DeckOp) => Promise<void>;
}) {
  const [shown, setShown] = useState(data);
  const [want, setWant] = useState<string | null>(null);   // the page being fetched
  useEffect(() => { setShown(data); setWant(null); }, [data]);
  const deck = parseDeck(shown);
  const pages = deck?.pages ?? [];
  const several = pages.length > 1;
  const page = several ? deck?.page : undefined;
  const pick = async (name: string) => {
    if (!readFile) return;
    setWant(name);
    onPage?.(name);
    try {
      setShown(await readFile(`${file.path}?as=slides${pageQuery(name)}`, true));
    } catch { /* what's shown stays */ } finally {
      setWant((w) => (w === name ? null : w));
    }
  };
  if (!deck) return null;
  return (
    <div className="flex h-full flex-col">
      {tabs && several && readFile && <PageTabs pages={pages.map((p) => p.name)} page={want ?? page ?? ""} onPick={(name) => void pick(name)} />}
      <div className="min-h-0 flex-1">
        {deck.count > 1
          // Slide ops apply only to the first page (a deck is one page).
          ? <DeckView data={shown} path={file.path} openFile={openFile} onReload={onReload}
                      onSlideOp={!page || page === pages[0]?.name ? onSlideOp : undefined}
                      onPage={readFile ? (name) => void pick(name) : undefined} />
          : deck.count === 1
            ? <DesignPicture file={file} src={deck.slides[0]} openFile={downloads ? openFile : undefined} page={page}
                             size={deck.sizes?.[0]} name={deck.names?.[0]} pages={pages.map((p) => p.name)}
                             onPage={readFile ? (name) => void pick(name) : undefined} />
            : <div className="flex h-full items-center justify-center text-sm text-muted-foreground" data-testid="page-empty">{t("pageEmpty")}</div>}
      </div>
    </div>
  );
}

// A one-frame design with no editor: its picture and downloads.
function DesignPicture({ file, src, openFile, page, size, name, pages, onPage }: {
  file: CanvasFile;
  src: string;
  openFile?: (path: string, silent?: boolean) => Promise<string>;
  page?: string;
  size?: number[];                     // the frame's own size: comments pin in its pixels
  name?: string;
  pages?: string[];
  onPage?: (page: string) => void;     // show another page (a comment is on it)
}) {
  const picture = useRef<HTMLImageElement>(null);
  const names = useMemo(() => [name ?? ""], [name]);
  const stem = file.name.replace(/\.fig$/i, "") + (page ? `-${page}` : "");
  const save = (as: "png" | "pdf") => openFile?.(`${file.path}?as=${as}${pageQuery(page)}`).then((url) => saveBlob(url, `${stem}.${as}`)).catch(() => {});
  const pill = "cursor-pointer rounded-full border border-border bg-background/90 px-4 py-2 text-xs font-medium text-foreground shadow-lg backdrop-blur transition-colors hover:bg-secondary";
  return (
    <div className="relative flex h-full items-center justify-center overflow-auto bg-secondary/40 p-4">
      <img ref={picture} src={src} alt={file.name} data-testid="design-picture" className="max-h-full max-w-full object-contain shadow-sm" />
      {/* Comments, where this page can comment. */}
      <CommentLayer path={file.path} picture={picture} size={size} frame={0} names={names} page={page} pages={pages} />
      <CommentButtons path={file.path} className="absolute end-3 top-3 z-10 rounded-lg border border-border bg-background/90 p-0.5 shadow backdrop-blur" />
      <CommentsList path={file.path} names={names} page={page} pages={pages} onPage={onPage} />
      {openFile && (
        <div className="absolute bottom-4 end-4 flex gap-2">
          <button onClick={() => save("png")} className={pill}>{t("downloadImage")}</button>
          <button onClick={() => save("pdf")} className={pill}>{t("downloadPdf")}</button>
        </div>
      )}
    </div>
  );
}

// A video on the canvas: the preview player, and Edit into the video editor (a full-page overlay)
// where it is offered and there is room for it. Done brings the preview back, fetched again.
function VideoComposition({ file, content, openFile, onDownload, onReload, videoEditor, writeFile }: {
  file: CanvasFile;
  content: string;
  openFile?: (path: string, silent?: boolean) => Promise<string>;
  onDownload?: () => void;
  onReload?: () => void;
  videoEditor?: VideoEditorApi;
  writeFile?: WriteFile;
}) {
  const [editing, setEditing] = useState(false);
  const [aside, setAside] = useState(false);     // stepped aside for Ask Cycls, still open
  const canEdit = !!videoEditor && !!writeFile && canEditVideo();
  return (
    <>
      <Suspense fallback={<LoadingBar />}>
        <CompositionView data={content} name={file.name} openFile={openFile} onDownload={onDownload}
                         editOpen={editing && aside}
                         onEdit={canEdit ? () => { setEditing(true); setAside(false); } : undefined} />
      </Suspense>
      {editing && videoEditor && writeFile && (
        <VideoEditorView path={file.path} name={file.name} api={videoEditor} writeFile={writeFile}
                         aside={aside} onAside={() => setAside(true)} onBack={() => setAside(false)}
                         onClose={() => { setEditing(false); setAside(false); onReload?.(); }} />
      )}
    </>
  );
}

export function CanvasDoc({ file, content, error, shared = false, readFile, openFile, resolveMedia, writeFile, deckOp, pollsFor, listFolders, fetchConnector, appData, designEditorUrl, designHost, videoEditor, reloadFile, onReload, onDownload, onShare }: {
  file: CanvasFile;
  resolveMedia?: (path: string) => Promise<string>;
  content: string | null;
  error: boolean;
  shared?: boolean;
  readFile?: (path: string, silent?: boolean) => Promise<string>;
  openFile?: (path: string, silent?: boolean) => Promise<string>;   // authed blob URL (a deck's downloads, its .fig)
  writeFile?: WriteFile;
  deckOp?: (path: string, body: DeckOp) => Promise<void>;          // a deck's slide moves / copies / deletes
  pollsFor?: (deck: string) => PollApi;   // live polls in a presented deck (the owner's)
  listFolders?: () => Promise<{ name: string; path: string }[]>;
  fetchConnector?: (name: string, path: string, init: { method: string; headers: Record<string, string>; body?: string }) => Promise<{ status: number; body: string; contentType: string }>;
  appData?: (slug: string, op: Record<string, unknown>) => Promise<unknown>;
  designEditorUrl?: string;   // when set, .fig opens the embedded editor
  designHost?: DesignHost;
  videoEditor?: VideoEditorApi;   // when set, a video has Edit (the video editor)
  reloadFile?: () => Promise<string>;   // fresh blob URL of this file (the .fig editor re-opens on it)
  onReload?: () => void;      // refetch this document (a deck whose slides changed)
  onDownload?: () => void;
  onShare?: () => void;
}) {
  const lang = codeLang(fileKind(file));
  if (content == null && !error) return <LoadingBar />;
  if (error) {
    // A failed Office conversion / render (service down, unconvertible, parse
    // error) degrades to the download card rather than a dead error — same as an
    // unrenderable file.
    if (isOffice(fileKind(file)) || isDocx(fileKind(file)) || isPresentation(fileKind(file)) || isDeck(fileKind(file)) || isDesignEditor(fileKind(file)) || isComposition(fileKind(file)))
      return <NoPreviewCard file={file} onDownload={onDownload} onShare={onShare} />;
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't load this file.</div>;
  }
  // A design deck → the deck viewer; `content` is its slide manifest.
  if (isDeck(fileKind(file))) {
    return content ? (
      <DeckView data={content} path={file.path} openFile={openFile} writeFile={shared ? undefined : writeFile}
                designEditorUrl={shared ? undefined : designEditorUrl} designHost={shared ? undefined : designHost} onReload={onReload}
                onSlideOp={shared || !deckOp ? undefined : (op) => deckOp(file.path, op)}
                pollsFor={shared ? undefined : pollsFor} />
    ) : null;
  }
  // A Video composition → the sandboxed player (composition-view.tsx), never the page itself. On a
  // shared page it is a download: the share route will not serve it to be played.
  if (isComposition(fileKind(file))) {
    if (shared) return <NoPreviewCard file={file} onDownload={onDownload} onShare={onShare} />;
    return content ? (
      <VideoComposition file={file} content={content} openFile={openFile} onDownload={onDownload} onReload={onReload}
                        videoEditor={videoEditor} writeFile={writeFile} />
    ) : null;
  }
  if (isHtml(fileKind(file))) {
    return <HtmlDoc file={file} content={content ?? ""} shared={shared} readFile={readFile} writeFile={writeFile} listFolders={listFolders} fetchConnector={fetchConnector} appData={appData} />;
  }
  // Word .docx renders natively as formatted HTML (docx-preview) from its raw
  // bytes — a document view, not a flat PDF.
  if (isDocx(fileKind(file))) {
    return content ? <DocxView url={content} /> : null;
  }
  // Presentations render as a slide viewer from the ?as=slides manifest (per-
  // slide images), not a flat PDF. `content` here is that JSON, fetched as text.
  if (isPresentation(fileKind(file))) {
    return content ? <SlidesView data={content} /> : null;
  }
  // A .fig → the embedded editor when one is configured; else `content` is its slide
  // manifest, shown read-only.
  if (isDesignEditor(fileKind(file))) {
    if (content && designEditorUrl) {
      return <DesignEditorView url={content} path={file.path} name={file.name}
                               editorUrl={designEditorUrl} writeFile={writeFile ?? (async () => {})}
                               reload={reloadFile} host={shared ? undefined : designHost} />;
    }
    const pictures = content ? parseDeck(content) : null;
    if (!pictures?.count && !((pictures?.pages?.length ?? 0) > 1)) return <NoPreviewCard file={file} onDownload={onDownload} onShare={onShare} />;
    return <DesignPages file={file} data={content!} readFile={readFile} openFile={openFile} downloads />;
  }
  // Office docs arrive here as a converted-PDF blob URL, so they ride the same
  // native PDF viewer (search / zoom / print, mobile open-in-tab).
  if (isPdf(fileKind(file)) || isOffice(fileKind(file))) {
    // Desktop's native inline viewer is the best PDF UX (search, zoom, print).
    // Phones can't EMBED PDFs (iOS iframes render page 1 only) but render them
    // fine on direct navigation — so on small screens the iframe doubles as a
    // first-page preview with an open button on top. Zero dependencies.
    return (
      <div className="relative h-full w-full">
        <iframe src={content ?? ""} title={file.name} className="h-full w-full border-0" />
        <a
          href={content ?? ""}
          target="_blank"
          rel="noopener noreferrer"
          className="sm:hidden absolute bottom-6 left-1/2 -translate-x-1/2 rounded-full border border-border bg-background/90 px-4 py-2 text-sm font-medium text-foreground shadow-lg backdrop-blur transition-colors hover:bg-secondary"
        >
          {t("openInTab")}
        </a>
      </div>
    );
  }
  if (isImage(fileKind(file))) {
    return (
      <div className="flex h-full items-center justify-center overflow-auto p-4">
        <img src={content ?? ""} alt={file.name} className="max-h-full max-w-full object-contain" />
      </div>
    );
  }
  if (isVideo(fileKind(file))) {
    return (
      <div className="flex h-full items-center justify-center bg-black">
        <video src={content ?? ""} controls className="max-h-full max-w-full" />
      </div>
    );
  }
  if (isAudio(fileKind(file))) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <audio src={content ?? ""} controls className="w-full max-w-xl" />
      </div>
    );
  }
  if (isSpreadsheet(fileKind(file))) {
    return content ? <SpreadsheetView url={content} name={file.name} /> : null;
  }
  if (is3d(fileKind(file))) {
    // model-viewer from CDN inside our own iframe shell — no npm dependency.
    // No sandbox: the srcDoc is our template, and an opaque origin couldn't
    // fetch the parent's blob URL.
    return content ? (
      <iframe
        srcDoc={`<!doctype html><html><head><meta charset="utf-8">
<script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
<style>html,body{margin:0;height:100%;overflow:hidden}
model-viewer{width:100vw;height:100vh;background:radial-gradient(ellipse at center,#1a1a1a 0%,#0a0a0a 100%)}</style>
</head><body><model-viewer src="${content}" camera-controls auto-rotate shadow-intensity="1" exposure="1.1" environment-image="neutral"></model-viewer></body></html>`}
        title={file.name}
        className="h-full w-full border-0"
      />
    ) : null;
  }
  if (isMd(fileKind(file))) {
    return (
      <div className="h-full overflow-y-auto px-6 py-5 sm:px-8">
        <TextPart text={content ?? ""} resolveMedia={resolveMedia} />
      </div>
    );
  }
  if (lang == null) {
    return <NoPreviewCard file={file} onDownload={onDownload} onShare={onShare} />;
  }
  return (
    <div className="h-full overflow-auto">
      <HighlightedCode code={content ?? ""} language={lang} />
    </div>
  );
}

// Open files as tabs, docked (desktop split pane) or as the overlay drawer.
export function Canvas({ tabs, active, docked, hidden, expanded, onToggleExpand, onCloseAll, onSelectTab, onCloseTab, onReorder, onHide, onAddFile, searchFiles, apps, onAddApp, readFile, openFile, writeFile, uploadFile, deckOp, pollsFor, listFolders, fetchConnector, appData, org, onShareFile, shareLinks, railWidth = 0, reloadKey, working, designEditorUrl, designHost, videoEditor, onNewDesign }: {
  tabs: CanvasFile[];
  active: string | null;
  docked: boolean;
  hidden?: boolean;
  expanded: boolean;
  working?: string[];   // paths being written — skeleton instead of content
  onToggleExpand: () => void;
  onCloseAll?: () => void;
  onSelectTab: (path: string) => void;
  onCloseTab: (path: string) => void;
  onReorder?: (tabs: CanvasFile[]) => void;
  onHide: () => void;
  onAddFile?: (path: string) => void;
  apps?: AppInfo[];
  onAddApp?: (app: AppInfo) => void;
  searchFiles?: (q: string) => Promise<{ name: string; path: string }[]>;
  readFile: (path: string) => Promise<string>;   // authed text fetch (md/html/code source)
  openFile: (path: string, silent?: boolean) => Promise<string>;    // authed blob URL (pdf / download / media)
  writeFile: WriteFile;  // overwrite (editor); binary for the .fig editor
  uploadFile?: (dir: string, file: File) => Promise<void>;   // images and videos dropped into the editor
  deckOp?: (path: string, body: DeckOp) => Promise<void>;        // a deck's slide moves / copies / deletes
  pollsFor?: (deck: string) => PollApi;   // live polls in a presented deck (the owner's)
  listFolders?: () => Promise<{ name: string; path: string }[]>;  // app save dialog
  fetchConnector?: (name: string, path: string, init: { method: string; headers: Record<string, string>; body?: string }) => Promise<{ status: number; body: string; contentType: string }>;
  appData?: (slug: string, op: Record<string, unknown>) => Promise<unknown>;   // an app's live call to a connector API
  org?: { id: string; name: string } | null;   // lets the share dialog offer the org audience
  onShareFile?: (path: string, audience: string) => Promise<string>;
  shareLinks?: ShareLinks;   // existing links: the Share popover shows one instead of making another
  railWidth?: number;   // pane docked to our right; the drag must account for it
  reloadKey?: number;  // bump to re-fetch the open document
  designEditorUrl?: string;   // embedded .fig editor base URL (config.design_editor_url)
  videoEditor?: VideoEditorApi;   // the video editor (config.video_editor): Edit on a video
  designHost?: DesignHost;
  onNewDesign?: (preset: string) => void;   // "New design" in the + menu
}) {
  const file = hidden ? null : tabs.find((f) => f.path === active) ?? tabs[tabs.length - 1] ?? null;
  // A design editor left behind stays mounted, hidden, until it has flushed. Noted
  // during render, not in an effect, so it never leaves the tree.
  const [draining, setDraining] = useState<CanvasFile[]>([]);
  // A video whose editor is open stays mounted too, hidden, while another tab is shown (the agent
  // opened the MP4 it rendered, or a page it wrote): the editor is a full-page overlay of its own,
  // still open — stepped aside, its Back to the editor still there — until Done. A video tab closed
  // meanwhile drains like a design.
  const [held, setHeld] = useState<CanvasFile[]>([]);
  const [shown, setShown] = useState<CanvasFile | null>(file);
  if ((file?.path ?? null) !== (shown?.path ?? null)) {
    setShown(file);
    if (shown && file && designEditorUrl && isDesignEditor(fileKind(shown))) {
      setDraining((d) => [...d.filter((x) => x.path !== shown.path), shown]);
    }
    if (shown && file && videoEditorOpen(shown.path)) {
      if (tabs.some((x) => x.path === shown.path)) setHeld((h) => [...h.filter((x) => x.path !== shown.path), shown]);
      else setDraining((d) => [...d.filter((x) => x.path !== shown.path), shown]);
    }
  }
  const closed = held.filter((f) => !tabs.some((x) => x.path === f.path));
  if (closed.length) {
    setHeld((h) => h.filter((f) => tabs.some((x) => x.path === f.path)));
    setDraining((d) => [...d.filter((x) => !closed.some((c) => c.path === x.path)), ...closed]);
  }
  useEffect(() => watchVideoEditors(() => setHeld((h) => {
    const open = h.filter((f) => videoEditorOpen(f.path));
    return open.length === h.length ? h : open;
  })), []);
  const flushing = useRef(new Set<string>());
  useEffect(() => {
    for (const f of draining) {
      if (flushing.current.has(f.path)) continue;
      flushing.current.add(f.path);
      void Promise.all([flushDesignEditor(f.path, 5000), flushVideoEditor(f.path, 5000)]).finally(() => {
        flushing.current.delete(f.path);
        setDraining((d) => d.filter((x) => x.path !== f.path));
      });
    }
  }, [draining]);
  // The last tab unmounts the canvas, leaving nothing to drain: its design or video editor flushes first.
  const closeTab = (path: string) => {
    if (tabs.length === 1 && (designEditorUrl || videoEditorOpen(path)))
      void Promise.all([flushDesignEditor(path, 1500), flushVideoEditor(path, 1500)]).then(() => onCloseTab(path));
    else onCloseTab(path);
  };
  const { width, startResize, resizing } = usePaneWidth("cycls_canvas_width", 560, 380, 420, railWidth, undefined, 1, 0.25);

  const inner = file && (
    <>
      <div className="flex h-11 shrink-0 items-center gap-1 border-b border-border px-2">
        <Reorder.Group as="div" axis="x" values={tabs} onReorder={(t) => onReorder?.(t)} className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {tabs.map((f) => {
            const on = f.path === file.path;
            const tint = extTint(f.name);
            return (
              <Reorder.Item
                as="div"
                value={f}
                key={f.path}
                role="button"
                onClick={() => onSelectTab(f.path)}
                className={cn(
                  "group flex min-w-20 max-w-44 flex-1 basis-0 cursor-pointer items-center gap-1.5 rounded-lg py-1 pl-2.5 pr-1 text-xs transition-colors",
                  on ? "bg-secondary text-foreground font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                )}
              >
                {f.icon || f.iconSrc || f.letter
                  ? <AppIcon app={f} className="size-3.5 rounded-[3px]" textClassName="text-[13px]" />
                  : tint && <span className="size-1.5 rounded-full" style={{ backgroundColor: tint }} />}
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); closeTab(f.path); }}
                  className={cn("shrink-0 rounded p-0.5 hover:bg-accent/20", on ? "" : "opacity-0 group-hover:opacity-100")}
                  aria-label={`Close ${f.name}`}
                >
                  <Icon name="x" className="size-3" />
                </button>
              </Reorder.Item>
            );
          })}
          {onAddFile && searchFiles && (
            <AddTab onAdd={onAddFile} searchFiles={searchFiles} apps={apps} onAddApp={onAddApp}
                    onNewDesign={designEditorUrl ? onNewDesign : undefined} />
          )}
        </Reorder.Group>
        <button
          onClick={onToggleExpand}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground cursor-pointer"
          aria-label={expanded ? t("collapse") : t("expand")}
          title={expanded ? t("collapse") : t("expand")}
        >
          <Icon name={expanded ? "collapse" : "expand"} className="size-4" />
        </button>
        {onCloseAll && (
          <button
            onClick={onCloseAll}
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground cursor-pointer"
            aria-label={t("close")}
            title={t("close")}
          >
            <Icon name="x" className="size-4" />
          </button>
        )}
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col">
        {[file, ...draining.filter((d) => d.path !== file.path),
          ...held.filter((h) => h.path !== file.path && !draining.some((d) => d.path === h.path))].map((f) => {
          const on = f.path === file.path;
          return (
            <div key={f.path} inert={!on} aria-hidden={on ? undefined : true}
                 className={on ? "flex min-h-0 flex-1 flex-col" : "pointer-events-none invisible absolute inset-0 flex flex-col"}>
              {on && working?.includes(f.path) ? (
                <CanvasWorking name={f.name} />
              ) : (
                <CanvasFileView
                  file={f}
                  readFile={readFile}
                  openFile={openFile}
                  writeFile={writeFile}
                  uploadFile={uploadFile}
                  deckOp={deckOp}
                  pollsFor={pollsFor}
                  listFolders={listFolders}
                  fetchConnector={fetchConnector}
                  appData={appData}
                  org={org}
                  onShareFile={onShareFile}
                  shareLinks={shareLinks}
                  reloadKey={reloadKey}
                  designEditorUrl={designEditorUrl}
                  designHost={designHost}
                  videoEditor={videoEditor}
                />
              )}
            </div>
          );
        })}
      </div>
    </>
  );

  if (docked) {
    return (
      <AnimatePresence initial={false}>
        {file && (
          <motion.aside
            key="canvas"
            dir="ltr"
            initial={{ width: 0 }}
            animate={expanded ? { width: "100%" } : { width }}
            exit={{ width: 0 }}
            transition={resizing ? { duration: 0 } : slide}
            className={cn("relative overflow-hidden", expanded ? "min-w-0 flex-1" : "shrink-0")}
          >
            <div
              className={cn("flex flex-col overflow-hidden bg-background",
                            expanded ? "h-full w-full" : "absolute inset-y-0 right-0")}
              style={expanded ? undefined : { width }}
            >
              {!expanded && (
                <div
                  onMouseDown={startResize}
                  className="absolute bottom-0 left-0 top-0 z-20 w-1.5 cursor-ew-resize hover:bg-accent/30"
                  aria-label="Resize canvas"
                />
              )}
              {inner}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    );
  }

  if (file && expanded) {
    return (
      <>
        <div className="fixed inset-0 z-[55] bg-black/30 backdrop-blur-[2px]" onClick={onHide} />
        <div dir="ltr" className="fixed inset-2 z-[60] flex flex-col overflow-hidden rounded-xl border border-border bg-background">
          {inner}
        </div>
      </>
    );
  }

  return (
    <AnimatePresence>
      {file && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[55] bg-black/30 backdrop-blur-[2px]"
            onClick={onHide}
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed bottom-1 right-1 top-1 z-[60] flex w-[calc(100%-0.5rem)] flex-col overflow-hidden rounded-xl border border-border bg-background sm:w-[720px] lg:w-[60vw] lg:max-w-[960px]"
            dir="ltr"
          >
            {inner}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

const WORKING_WORDS = {
  en: ["Writing", "Crafting", "Brewing", "Weaving", "Sculpting", "Conjuring", "Cooking", "Polishing"],
  ar: ["أكتب", "أشتغل", "أصمّم", "أتفنن", "أبني", "أظبّط", "أنسّق", "ألمّع"],
} as const;

function CanvasWorking({ name }: { name: string }) {
  const widths = ["45%", "92%", "84%", "88%", "62%", "", "78%", "86%", "70%", "40%"];
  const words = WORKING_WORDS[getLang()] || WORKING_WORDS.en;
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1600);
    return () => clearInterval(id);
  }, []);
  const word = words[tick % words.length];
  return (
    <div className="flex h-full flex-col">
      <LoadingBar active />
      <div className="flex flex-1 flex-col items-center justify-center gap-10 px-8">
        <div className="w-full max-w-md space-y-3.5">
          {widths.map((w, i) => (w === ""
            ? <div key={i} className="h-2" />
            : <div key={i} className="h-3 animate-pulse rounded bg-secondary" style={{ width: w, animationDelay: `${i * 140}ms` }} />))}
        </div>
        <div className="flex flex-col items-center gap-1 text-center">
          <div className="h-8 overflow-hidden">
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.div
                key={word}
                initial={{ y: 18, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: -18, opacity: 0 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                className="text-xl font-medium text-foreground"
              >
                {word}
              </motion.div>
            </AnimatePresence>
          </div>
          <span className="text-sm text-muted-foreground" dir="auto">{name}</span>
        </div>
      </div>
    </div>
  );
}

// The menu is position:fixed from the button's rect so the pane's
// overflow-hidden can't clip it, and clamped to the window (the + sits near its edge).
const ADD_MENU_W = 288;   // w-72
export const addMenuLeft = (buttonLeft: number, viewport: number) =>
  Math.max(8, Math.min(buttonLeft, viewport - ADD_MENU_W - 8));

function AddTab({ onAdd, searchFiles, apps = [], onAddApp, onNewDesign }: {
  onAdd: (path: string) => void;
  searchFiles: (q: string) => Promise<{ name: string; path: string }[]>;
  apps?: AppInfo[];
  onAddApp?: (app: AppInfo) => void;
  onNewDesign?: (preset: string) => void;
}) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ name: string; path: string }[]>([]);
  const needle = q.trim().toLowerCase();
  useEscape(() => setPos(null), pos != null);
  const matchedApps = onAddApp
    ? apps.filter((a) => !needle || a.name.toLowerCase().includes(needle) || a.slug.includes(needle))
    : [];

  useEffect(() => {
    if (!pos) return;
    let dead = false;
    searchFiles(q).then((r) => { if (!dead) setResults(r); });
    return () => { dead = true; };
  }, [pos != null, q, searchFiles]);

  const toggle = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (pos) { setPos(null); return; }
    const r = e.currentTarget.getBoundingClientRect();
    setQ("");
    setPos({ x: addMenuLeft(r.left, window.innerWidth), y: r.bottom + 4 });
  };

  return (
    <>
      <button
        onClick={toggle}
        className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
        aria-label={t("openAFile")}
        title={t("openAFile")}
      >
        <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
      </button>
      {pos && createPortal(
        <>
          <div className="fixed inset-0 z-[70]" onClick={() => setPos(null)} />
          <div className="fixed z-[70] w-72 overflow-hidden rounded-xl border border-border bg-background shadow-xl" style={{ left: pos.x, top: pos.y }}>
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("searchFilesPlaceholder")}
              className="w-full border-b border-border bg-transparent px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
            {onNewDesign && !needle && (
              <div className="border-b border-border px-3 py-2">
                <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">{t("newDesign")}</div>
                <div className="flex flex-wrap gap-1">
                  {DESIGN_PRESETS.map((p) => (
                    <button
                      key={p.key}
                      data-testid={`new-design-${p.key}`}
                      onClick={() => { onNewDesign(p.key); setPos(null); }}
                      title={`${p.size[0]}×${p.size[1]}`}
                      className="cursor-pointer rounded-md border border-border px-2 py-1 text-[11px] text-foreground transition-colors hover:bg-secondary/80"
                    >
                      {t(p.label)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="max-h-64 overflow-y-auto py-1">
              {matchedApps.length > 0 && (
                <>
                  {matchedApps.map((a) => (
                    <button
                      key={a.slug}
                      onClick={() => { onAddApp?.(a); setPos(null); }}
                      className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-secondary/80"
                    >
                      <AppIcon app={a} className="size-3.5 rounded-[3px]" textClassName="text-[13px]" />
                      <span className="truncate">{a.name}</span>
                    </button>
                  ))}
                  {results.length > 0 && <div className="my-1 border-t border-border" />}
                </>
              )}
              {results.length === 0 && matchedApps.length === 0 ? (
                <div className="px-3 py-3 text-center text-xs text-muted-foreground">—</div>
              ) : results.map((r) => {
                const tint = extTint(r.name);
                return (
                  <button
                    key={r.path}
                    onClick={() => { onAdd(r.path); setPos(null); }}
                    className="flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-secondary/80"
                  >
                    <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: tint || "var(--color-muted-foreground)" }} />
                    <span className="truncate" dir="ltr">{r.path}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </>,
        document.body,
      )}
    </>
  );
}

// Keyed by path from the parent, so per-file state resets on tab switch.
function CanvasFileView({ file, readFile, openFile, writeFile, uploadFile, deckOp, pollsFor, listFolders, fetchConnector, appData, org, onShareFile, shareLinks, reloadKey, designEditorUrl, designHost, videoEditor }: {
  file: CanvasFile;
  uploadFile?: (dir: string, file: File) => Promise<void>;
  readFile: (path: string, silent?: boolean) => Promise<string>;
  openFile: (path: string, silent?: boolean) => Promise<string>;
  writeFile: WriteFile;
  deckOp?: (path: string, body: DeckOp) => Promise<void>;
  pollsFor?: (deck: string) => PollApi;   // live polls in a presented deck (the owner's)
  listFolders?: () => Promise<{ name: string; path: string }[]>;
  fetchConnector?: (name: string, path: string, init: { method: string; headers: Record<string, string>; body?: string }) => Promise<{ status: number; body: string; contentType: string }>;
  appData?: (slug: string, op: Record<string, unknown>) => Promise<unknown>;
  org?: { id: string; name: string } | null;
  onShareFile?: (path: string, audience: string) => Promise<string>;
  shareLinks?: ShareLinks;
  reloadKey?: number;
  designEditorUrl?: string;
  videoEditor?: VideoEditorApi;
  designHost?: DesignHost;
}) {
  const [bump, setBump] = useState(0);   // a document asked to refetch itself (a deck was edited)
  const { content, setContent, error } = useFileContent(file, readFile, openFile, (reloadKey ?? 0) + bump, !designEditorUrl);
  const onReload = useCallback(() => setBump((n) => n + 1), []);
  // The agent changed this file mid-turn (a Video edit): fetch it again now, not when the turn ends.
  useEffect(() => {
    const onRefresh = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === file.path) setBump((n) => n + 1);
    };
    window.addEventListener("cycls:canvas-refresh", onRefresh);
    return () => window.removeEventListener("cycls:canvas-refresh", onRefresh);
  }, [file.path]);
  const resolveMedia = useMemo(() => mediaResolver(file.path, openFile), [file.path, openFile]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const md = isMd(fileKind(file));
  const lang = codeLang(fileKind(file));
  const deck = isDeck(fileKind(file));
  const isText = !deck && (md || lang != null);   // text-based: editable + copyable (a deck's content is its slides)
  const dirs = file.path.split("/").slice(0, -1);

  const copy = () => {
    if (content == null) return;
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // A design's preview: what it looks like without the editor around it.
  const design = isDesignEditor(fileKind(file)) && !!designEditorUrl;
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);     // its slide manifest
  const [previewFailed, setPreviewFailed] = useState(false);
  // With several pages, they are tabs above the design, in the editor and the preview alike.
  const pagesInfo = useDesignPages(file.path);
  const several = design && !!pagesInfo && pagesInfo.pages.length > 1;
  const previewPage = useRef<string | undefined>(undefined);
  const [shownPage, setShownPage] = useState<string | undefined>(undefined);
  // No default from the ref: falling back to the first page must not retry the failed one.
  const loadPreview = useCallback(async (page: string | undefined) => {
    previewPage.current = page;
    setShownPage(page);
    try {
      setPreview(await readFile(`${file.path}?as=slides${pageQuery(page)}`, true));
      setPreviewFailed(false);
    } catch {
      if (page) return loadPreview(undefined);   // a page renamed or removed since: the first one
      setPreviewFailed(true);
    }
  }, [readFile, file.path]);
  // The editor follows too, so Edit comes back on that page.
  const pickPage = (page: string) => {
    showDesignPage(file.path, page);
    if (previewing) void loadPreview(page);
  };
  const showPreview = async () => {
    setPreview(null);
    setPreviewFailed(false);
    setPreviewing(true);
    track("design_previewed", {});
    await flushDesignEditor(file.path, 3000);   // what's unsaved is in the preview
    await loadPreview(designPage(file.path));
  };
  useEffect(() => {   // an agent edit while previewing is already saved: show it
    if (!previewing) return;
    const onCommand = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === file.path) void loadPreview(previewPage.current);
    };
    window.addEventListener("cycls:design-command", onCommand);
    return () => window.removeEventListener("cycls:design-command", onCommand);
  }, [previewing, file.path, loadPreview]);

  const download = () => openFile(file.path).then((url) => saveBlob(url, file.path.split('/').pop() || file.name)).catch(() => {});
  // Rendered from the saved file by the design service, so the editor flushes first.
  const downloadDesignAs = async (as: "png" | "pdf") => {
    await flushDesignEditor(file.path, 3000);
    track("design_exported", { format: as, files: 1 });
    const page = previewing ? previewPage.current : designPage(file.path);
    openFile(`${file.path}?as=${as}${pageQuery(page)}`)
      .then((url) => saveBlob(url, `${file.name.replace(/\.fig$/i, "")}${page ? `-${page}` : ""}.${as}`)).catch(() => {});
  };
  const reloadFile = useCallback(() => openFile(file.path), [openFile, file.path]);

  // Open HTML as a standalone page (its own browsing context) — a stable,
  // full-window render that doesn't reflow with the drawer, plus print/PDF.
  const openInTab = () => {
    if (content == null) return;
    window.open(URL.createObjectURL(new Blob([content], { type: "text/html" })), "_blank");
  };

  const startEdit = () => { setDraft(content ?? ""); setEditing(true); };
  useEffect(() => { if (file.writable && content === "") { setDraft(""); setEditing(true); } }, [file.writable, content]);

  const save = async () => {
    setSaving(true);
    try {
      await writeFile(file.path, draft);
      setContent(draft);
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  // Tab inserts two spaces instead of moving focus.
  const onEditorKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const el = e.currentTarget;
    const s = el.selectionStart, en = el.selectionEnd;
    setDraft((d) => d.slice(0, s) + "  " + d.slice(en));
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = s + 2; });
  };

  const headerBtn = "flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer";

  return (
    <>
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border px-4 sm:px-6 py-3">
        <div className="flex min-w-0 items-center gap-1 text-sm">
          {dirs.map((seg, i) => (
            <span key={i} className="flex shrink-0 items-center gap-1 text-muted-foreground">
              <span className="max-w-24 truncate">{seg}</span>
              <Icon name="chevron-right" className="size-3 text-muted-foreground/50" strokeWidth={2.5} />
            </span>
          ))}
          <span className="min-w-0 truncate font-medium text-foreground">{file.name}</span>
        </div>
        {lang && lang !== "text" && !deck && (
          <span className="shrink-0 rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{lang}</span>
        )}
        <div className="flex-1" />
        {editing ? (
          <>
            <button onClick={() => setEditing(false)} className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer px-2 py-1">
              {t("cancel")}
            </button>
            <button onClick={save} disabled={saving} className="text-xs font-medium text-foreground bg-secondary hover:bg-secondary/80 rounded-md px-3 py-1.5 transition-colors cursor-pointer disabled:opacity-50">
              {saving ? t("saving") : t("save")}
            </button>
          </>
        ) : (
          <>
            {saved && <span className="text-xs text-muted-foreground">{t("saved")}</span>}
            {isText && content != null && (
              <button onClick={startEdit} className="text-xs font-medium text-foreground bg-secondary hover:bg-secondary/80 rounded-md px-3 py-1.5 transition-colors cursor-pointer">
                {t("edit")}
              </button>
            )}
            {design && !previewing && <DesignPresenceRow path={file.path} />}
            {/* An older editor can't draw pins: comment on the preview instead. */}
            {design && !previewing && <CommentButtons path={file.path}
                                                      onComment={(adding) => { if (adding && !designEditorComments(file.path)) void showPreview(); }}
                                                      onList={() => { if (!designEditorComments(file.path)) void showPreview(); }} />}
            {design && <EditPreviewSwitch previewing={previewing} onEdit={() => setPreviewing(false)} onPreview={() => void showPreview()} />}
            {/* Invisible, not removed, in a preview so the switch beside it doesn't jump. */}
            {design && canFullscreen() && (
              <button onClick={() => fullscreenDesignEditor(file.path)} className={cn(headerBtn, previewing && "invisible")}
                      disabled={previewing} aria-hidden={previewing || undefined} tabIndex={previewing ? -1 : undefined}
                      aria-label={t("fullScreen")} title={t("fullScreen")}>
                <svg className="size-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 8.25v-4.5h4.5m7.5 0h4.5v4.5m0 7.5v4.5h-4.5m-7.5 0h-4.5v-4.5" />
                </svg>
              </button>
            )}
            {(() => {
              const items = [
                ...(onShareFile ? [{ label: t("share"), onClick: () => setShareOpen(true) }] : []),
                ...(isText && content != null ? [{ label: copied ? t("copied") : t("copy"), onClick: copy }] : []),
                // Not a composition: as a page in its own tab its script would run on this origin.
                ...(isHtml(fileKind(file)) && !isComposition(fileKind(file)) && content != null
                  ? [{ label: t("openInTab"), onClick: openInTab }] : []),
                ...(md ? [{ label: t("exportPdf"), onClick: () => window.print() }] : []),
                ...(isDesignEditor(fileKind(file)) && designEditorUrl && designHost?.listVersions
                  ? [{ label: t("versionHistory"), onClick: () => setHistoryOpen(true) }] : []),
                ...(isDesignEditor(fileKind(file)) && designEditorUrl ? [
                  { label: t("downloadPng"), onClick: () => void downloadDesignAs("png") },
                  { label: t("downloadPdf"), onClick: () => void downloadDesignAs("pdf") },
                  { label: t("downloadFig"), onClick: download },
                ] : [{ label: t("download"), onClick: download }]),
              ];
              return (
                <div className="relative shrink-0">
                  <button onClick={() => setMenuOpen((o) => !o)} className={headerBtn}
                          aria-label={t("more")} title={t("more")}>
                    <svg className="size-4" viewBox="0 0 24 24" fill="currentColor">
                      <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
                    </svg>
                  </button>
                  {menuOpen && <DropdownMenu onClose={() => setMenuOpen(false)} items={items} />}
                </div>
              );
            })()}
          </>
        )}
      </div>

      {several && (
        <PageTabs pages={pagesInfo!.pages} page={(previewing ? shownPage : undefined) ?? pagesInfo!.page} onPick={pickPage} />
      )}

      {/* Body */}
      <div className="relative flex-1 overflow-hidden">
        {historyOpen && designHost && (
          <VersionHistory path={file.path} host={designHost} onClose={() => setHistoryOpen(false)} />
        )}
        {editing && md && content != null && !PLAIN_MD.test(content) ? (
          <Suspense fallback={<LoadingBar />}>
            <MdEditor value={draft} onChange={setDraft} placeholder={file.writable ? t("instructionsPlaceholder") : undefined}
                      resolveMedia={resolveMedia} upload={uploadFile && (async (f) => {
                        const name = `${Date.now().toString(36)}-${f.name.replace(/[^\p{L}\p{N}._-]+/gu, "-")}`;   // nothing markdown reads as syntax
                        await uploadFile(`${file.path.slice(0, file.path.lastIndexOf("/") + 1)}media`, new File([f], name, { type: f.type }));
                        return `media/${name}`;   // beside the document, relative to it
                      })} />
          </Suspense>
        ) : editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onEditorKey}
            placeholder={file.writable ? t("instructionsPlaceholder") : undefined}
            spellCheck={false}
            className="h-full w-full resize-none border-0 bg-background px-4 py-4 sm:px-6 font-mono text-[13px] leading-relaxed text-foreground focus:outline-none"
          />
        ) : file.writable && content === "" ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-6">
            <p className="max-w-sm whitespace-pre-line text-sm leading-relaxed text-muted-foreground" dir="auto">{t("instructionsPlaceholder")}</p>
            <button onClick={startEdit} className="rounded-md bg-secondary px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary/80 cursor-pointer">
              {t("edit")}
            </button>
          </div>
        ) : (
          <>
            {/* Hidden, not unmounted, under a preview: it keeps its state and saves. */}
            <div className={previewing ? "invisible absolute inset-0" : "h-full"} inert={previewing} aria-hidden={previewing || undefined}>
              <CanvasDoc file={file} content={content} error={error} readFile={readFile} openFile={openFile} resolveMedia={resolveMedia} writeFile={writeFile} deckOp={deckOp} pollsFor={pollsFor} listFolders={listFolders}
                         fetchConnector={fetchConnector}
                         appData={appData}
                         designEditorUrl={designEditorUrl} designHost={designHost} videoEditor={videoEditor} reloadFile={reloadFile} onReload={onReload}
                         onDownload={download} onShare={onShareFile ? () => setShareOpen(true) : undefined} />
            </div>
            {previewing && (() => {
              const pictures = preview ? parseDeck(preview) : null;
              return (
                <div className="absolute inset-0 bg-background" data-testid="design-preview">
                  {previewFailed || (preview != null && !pictures?.count && !((pictures?.pages?.length ?? 0) > 1)) ? <NoPreviewCard file={file} onDownload={download} />
                    : !pictures ? <LoadingBar />
                    // Picking a page moves the editor too; downloads live in the ⋮ menu.
                    : <DesignPages file={file} data={preview!} readFile={readFile} openFile={openFile} tabs={!several}
                                   onPage={(page) => { previewPage.current = page; setShownPage(page); showDesignPage(file.path, page); }}
                                   onReload={() => void loadPreview(previewPage.current)}
                                   onSlideOp={deckOp ? (op) => deckOp(file.path, op) : undefined} />}
                </div>
              );
            })()}
          </>
        )}
      </div>

      {/* Print-only copy for Export PDF (md). Lives at body level so the drawer's
          fixed/transform layout doesn't distort it; hidden except when printing. */}
      {md && content != null && createPortal(
        <div className="print-root">
          <div className="prose mx-auto max-w-[46rem] p-8">
            <TextPart text={content} resolveMedia={resolveMedia} />
          </div>
        </div>,
        document.body,
      )}

      {shareOpen && onShareFile && (
        <ShareDialog
          onClose={() => setShareOpen(false)}
          mode="file"
          subtitle={file.name}
          org={org}
          onShare={(audience) => onShareFile(file.path, audience)}
          path={`file/${file.path}`}
          links={shareLinks}
        />
      )}
    </>
  );
}
