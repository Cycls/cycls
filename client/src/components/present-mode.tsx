import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { AnimatePresence, motion } from "framer-motion";
import { slideKeyTarget } from "../hooks/use-slide-nav";
import { t } from "../lib/i18n";

// Presents a deck full screen: one slide at a time, each entering with its own
// transition (fade / slide / none), click or the keyboard to move on.
//
// It's a portal on document.body — the canvas pane is overflow-hidden inside a
// transformed drawer, which would clip a fixed element — and it asks for real
// fullscreen (a browser may refuse; it then fills the window). While it's up it
// owns the keyboard: a capture-phase listener on window takes every key before
// anything underneath, so chat's global Escape (which closes the whole canvas)
// never sees the Escape that ends the presentation.
//
//   → ↓ Space PageDown Enter   next          ← ↑ PageUp Backspace   previous
//   Home / End                 first / last  N   speaker notes       G   grid
//   P                          presenter view (current + next slide, notes, timer)
//   Esc                        leave (or close the grid)

export interface PresentDeck {
  slides: string[];          // image URLs (data: URIs from the slide manifest)
  notes?: string[];
  titles?: string[];
  transitions?: string[];    // per slide: "fade" | "slide" | "none" (default fade)
}

type Kind = "fade" | "slide" | "none";
const kindOf = (deck: PresentDeck, i: number): Kind => {
  const k = deck.transitions?.[i];
  return k === "slide" || k === "none" ? k : "fade";
};

// A slide enters by its own transition; `dir` is +1 going forward, -1 back.
const variants = {
  enter: ({ kind, dir }: { kind: Kind; dir: number }) =>
    kind === "slide" ? { x: `${dir * 100}%`, opacity: 1 } : { x: 0, opacity: kind === "fade" ? 0 : 1 },
  center: { x: 0, opacity: 1 },
  exit: ({ kind, dir }: { kind: Kind; dir: number }) =>
    kind === "slide" ? { x: `${-dir * 100}%`, opacity: 1 } : { x: 0, opacity: kind === "fade" ? 0 : 1 },
};
const timing = (kind: Kind) => ({ duration: kind === "none" ? 0 : kind === "slide" ? 0.45 : 0.35, ease: "easeOut" as const });

// `onClose` gets the slide it ended on, so the viewer underneath can land there.
export function PresentMode({ deck, start = 0, onClose }: { deck: PresentDeck; start?: number; onClose: (last: number) => void }) {
  const count = deck.slides.length;
  const [index, setIndex] = useState(() => Math.max(0, Math.min(count - 1, start)));
  const [dir, setDir] = useState(1);
  const [ended, setEnded] = useState(false);          // past the last slide: the end screen
  const [notesOpen, setNotesOpen] = useState(false);
  const [gridOpen, setGridOpen] = useState(false);
  const [chrome, setChrome] = useState(true);         // controls + hint, hidden when idle
  const ref = useRef<HTMLDivElement>(null);
  const state = useRef({ index, ended, gridOpen });
  state.current = { index, ended, gridOpen };
  const closed = useRef(false);
  const wasFull = useRef(false);
  const presenter = useRef<{ win: Window; root: Root } | null>(null);
  const startedAt = useRef(Date.now());
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const close = useCallback(() => {
    if (closed.current) return;
    closed.current = true;
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    onCloseRef.current(state.current.index);
  }, []);

  const go = useCallback((to: number) => {
    const cur = state.current.index;
    const next = Math.max(0, Math.min(count - 1, to));
    setEnded(false);
    if (next === cur) return;
    setDir(next > cur ? 1 : -1);
    setIndex(next);
  }, [count]);
  const forward = useCallback(() => {
    const { index: i, ended: done } = state.current;
    if (done) close();
    else if (i >= count - 1) setEnded(true);
    else go(i + 1);
  }, [count, go, close]);
  const back = useCallback(() => {
    if (state.current.ended) setEnded(false);
    else go(state.current.index - 1);
  }, [go]);

  const [presenterTick, setPresenterTick] = useState(0);   // re-render the presenter window
  const openPresenter = useCallback(() => {
    const open = presenter.current;
    if (open && !open.win.closed) { open.win.focus(); return; }
    const win = window.open("", "cycls-presenter", "width=1180,height=720");
    if (!win) return;                                   // a popup blocker said no
    win.document.title = t("presenterView");
    win.document.body.style.cssText = "margin:0;background:#0b0b0c;color:#e8e8e8;font-family:system-ui,-apple-system,Segoe UI,sans-serif";
    win.document.body.innerHTML = '<div id="presenter-root"></div>';
    const root = createRoot(win.document.getElementById("presenter-root")!);
    presenter.current = { win, root };
    win.addEventListener("keydown", (e) => onKeyRef.current(e));   // drive the deck from the presenter window
    win.addEventListener("pagehide", () => { if (presenter.current?.win === win) presenter.current = null; });
    setPresenterTick((n) => n + 1);
  }, []);

  const onKey = useCallback((e: KeyboardEvent) => {
    // Present mode is modal: nothing underneath gets the key (chat's Escape
    // closes the canvas; the slide viewer's own keys would page it twice).
    e.stopPropagation();
    e.stopImmediatePropagation();
    const k = e.key;
    if (k === "Escape") {
      e.preventDefault();
      if (state.current.gridOpen) setGridOpen(false);
      else close();
      return;
    }
    if (k === "n" || k === "N") { e.preventDefault(); setNotesOpen((o) => !o); return; }
    if (k === "g" || k === "G") { e.preventDefault(); setGridOpen((o) => !o); return; }
    if (k === "p" || k === "P") { e.preventDefault(); openPresenter(); return; }
    if (state.current.gridOpen) return;
    if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " " || k === "Spacebar" || k === "Enter") {
      e.preventDefault();
      forward();
      return;
    }
    if (k === "Backspace") { e.preventDefault(); back(); return; }
    const to = slideKeyTarget(k, state.current.index, count);
    if (to != null) { e.preventDefault(); go(to); }
  }, [close, forward, back, go, count, openPresenter]);
  const onKeyRef = useRef(onKey);
  onKeyRef.current = onKey;

  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKeyRef.current(e);
    window.addEventListener("keydown", listener, true);
    return () => window.removeEventListener("keydown", listener, true);
  }, []);

  // Real fullscreen when the browser allows it; leaving it (the browser's own Esc)
  // leaves present mode too.
  useEffect(() => {
    const onChange = () => {
      if (document.fullscreenElement) wasFull.current = true;
      else if (wasFull.current) close();
    };
    document.addEventListener("fullscreenchange", onChange);
    ref.current?.requestFullscreen?.().catch(() => {});
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [close]);

  // The controls fade after a moment of stillness; a mouse move brings them back.
  useEffect(() => {
    if (!chrome) return;
    const id = window.setTimeout(() => setChrome(false), 2500);
    return () => window.clearTimeout(id);
  }, [chrome, index]);

  // The presenter window follows the deck; it closes with present mode.
  useEffect(() => {
    const p = presenter.current;
    if (!p || p.win.closed) return;
    p.root.render(<PresenterView deck={deck} index={index} ended={ended} startedAt={startedAt.current}
                                 onPrev={back} onNext={forward} />);
  }, [deck, index, ended, presenterTick, back, forward]);
  useEffect(() => () => {
    const p = presenter.current;
    if (p) { p.root.unmount(); if (!p.win.closed) p.win.close(); }
  }, []);

  if (count === 0) return null;
  const kind = kindOf(deck, index);
  const note = deck.notes?.[index]?.trim();

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={t("present")}
      data-testid="present-mode"
      className="fixed inset-0 z-[200] select-none overflow-hidden bg-black"
      onMouseMove={() => setChrome(true)}
    >
      <div className="absolute inset-0" onClick={forward}>
        <AnimatePresence initial={false} custom={{ kind, dir }}>
          {!ended && (
            <motion.div
              key={index}
              custom={{ kind, dir }}
              variants={variants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={timing(kind)}
              className="absolute inset-0 flex items-center justify-center"
            >
              <img src={deck.slides[index]} alt={deck.titles?.[index] || `Slide ${index + 1}`}
                   draggable={false} className="max-h-full max-w-full object-contain" />
            </motion.div>
          )}
        </AnimatePresence>
        {ended && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-white/60">{t("endOfDeck")}</div>
        )}
      </div>

      {notesOpen && !gridOpen && (
        <div className="absolute inset-x-0 bottom-0 max-h-[35%] overflow-y-auto bg-black/85 px-8 py-5 text-lg leading-relaxed text-white/90 backdrop-blur"
             dir="auto" onClick={(e) => e.stopPropagation()}>
          <div className="mb-1 text-xs uppercase tracking-wider text-white/40">{t("speakerNotes")}</div>
          <div className="whitespace-pre-wrap">{note || t("noNotes")}</div>
        </div>
      )}

      {gridOpen && (
        <div data-testid="present-grid" className="absolute inset-0 overflow-y-auto bg-black/90 p-8" onClick={() => setGridOpen(false)}>
          <div className="mx-auto grid max-w-6xl grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {deck.slides.map((src, i) => (
              <button key={i} onClick={(e) => { e.stopPropagation(); go(i); setGridOpen(false); }}
                      className={`overflow-hidden rounded-md border-2 text-left ${i === index ? "border-white" : "border-transparent hover:border-white/40"}`}>
                <img src={src} alt={`Slide ${i + 1}`} className="w-full" draggable={false} />
                <span className="block bg-black px-2 py-1 text-xs text-white/70">{i + 1}{deck.titles?.[i] ? ` · ${deck.titles[i]}` : ""}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className={`pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 px-5 pb-4 transition-opacity duration-300 ${chrome ? "opacity-100" : "opacity-0"}`}>
        <span className="text-xs text-white/50">{t("presentHint")}</span>
        <div className="pointer-events-auto flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-xs text-white/80 backdrop-blur">
          <button onClick={back} className="rounded-full px-2 py-1 hover:bg-white/10" aria-label="Previous">‹</button>
          <span data-testid="present-counter" className="tabular-nums">{index + 1} / {count}</span>
          <button onClick={forward} className="rounded-full px-2 py-1 hover:bg-white/10" aria-label={t("next")}>›</button>
          <span className="mx-1 h-4 w-px bg-white/20" />
          <button onClick={() => setNotesOpen((o) => !o)} className="rounded-full px-2 py-1 hover:bg-white/10">{t("speakerNotes")}</button>
          <button onClick={() => setGridOpen((o) => !o)} className="rounded-full px-2 py-1 hover:bg-white/10">{t("slidesGrid")}</button>
          <button onClick={openPresenter} className="rounded-full px-2 py-1 hover:bg-white/10">{t("presenterView")}</button>
          <button onClick={close} className="rounded-full px-2 py-1 hover:bg-white/10" aria-label={t("close")}>✕</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// The presenter's own window: the slide now showing, the next one, the notes, and
// a timer. Rendered from the presenting page into the popup (a React root of its
// own, so its clicks work) — plain inline styles, since the popup has none of ours.
function PresenterView({ deck, index, ended, startedAt, onPrev, onNext }: {
  deck: PresentDeck; index: number; ended: boolean; startedAt: number; onPrev: () => void; onNext: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const secs = Math.floor((now - startedAt) / 1000);
  const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const count = deck.slides.length;
  const next = index + 1 < count ? deck.slides[index + 1] : null;
  const note = deck.notes?.[index]?.trim();
  const box: React.CSSProperties = { background: "#000", borderRadius: 8, overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" };
  const button: React.CSSProperties = { background: "#222", color: "#eee", border: "1px solid #333", borderRadius: 6, padding: "6px 14px", fontSize: 14, cursor: "pointer" };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 16, padding: 16, height: "100vh", boxSizing: "border-box" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
        <div style={{ ...box, flex: 1, minHeight: 0 }}>
          {ended ? <span style={{ color: "#888" }}>{t("endOfDeck")}</span>
                 : <img src={deck.slides[index]} alt="" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button style={button} onClick={onPrev}>‹ {t("previous")}</button>
          <button style={button} onClick={onNext}>{t("next")} ›</button>
          <span style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums", color: "#aaa" }}>
            {t("slideLabel")} {Math.min(index + 1, count)} / {count} · {clock}
          </span>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
        <div style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 1, color: "#888" }}>{t("next")}</div>
        <div style={{ ...box, aspectRatio: "16 / 9" }}>
          {next ? <img src={next} alt="" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
                : <span style={{ color: "#666", fontSize: 13 }}>{t("endOfDeck")}</span>}
        </div>
        <div style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 1, color: "#888" }}>{t("speakerNotes")}</div>
        <div dir="auto" style={{ flex: 1, overflowY: "auto", fontSize: 20, lineHeight: 1.5, whiteSpace: "pre-wrap", color: note ? "#eee" : "#666" }}>
          {note || t("noNotes")}
        </div>
      </div>
    </div>
  );
}
