import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Icon } from "./icon";
import { t, getLang } from "../lib/i18n";
import { track, setPerson, flagsProvider } from "../lib/analytics";
import { cn } from "../lib/utils";
import {
  initNotifications, pushProvider, pushStatus, requestPush, answerResult,
  promptSnoozed, snoozePrompt, SNOOZE_DAYS,
} from "../lib/notifications";
import type { AppConfig } from "../hooks/use-chat";

// Two surfaces, one queue each (docs/notes/engagement.md). The modal is
// What's new; the corner holds one small card at a time — tips first, then
// the push prompt. The platform decides who and when, through whichever
// flags provider is on the pipe: the `announcements` flag's payload is the
// list, `notification_prompt` gates the prompt. We decide how it looks.

export type Announcement = {
  id: string; type: "modal" | "corner";
  tag?: string; tagColor?: string; title: string; body?: string; image?: string; cta?: string; url?: string;
  items?: { title: string; body?: string; image?: string }[];
  immediate?: boolean;
};

type Raw = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : undefined);
const pick = (o: Raw, key: string, lang: string) => (lang === "ar" ? str(o[`${key}_ar`]) : undefined) ?? str(o[key]);
// A color, not a stylesheet: hex, rgb()/hsl(), or a plain name — it lands in an inline style.
const COLOR = /^(#[0-9a-f]{3,8}|(rgb|hsl)a?\([\d.,%\s/]+\)|[a-z]{3,20})$/i;
const color = (v: unknown) => { const c = str(v); return c && COLOR.test(c) ? c : undefined; };
/** Dark or light text over a hex color; anything else gets white. */
export function onColor(bg: string) {
  const m = bg.match(/^#([0-9a-f]{3}|[0-9a-f]{6})/i);
  if (!m) return "#fff";
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#111" : "#fff";
}

/** The flag payload as cards to show: localized, inside their window, not yet seen. */
export function parseAnnouncements(payload: unknown, seen: Set<string>, lang: string, now = Date.now()): Announcement[] {
  const list: unknown[] = Array.isArray(payload) ? payload
    : payload && typeof payload === "object" && Array.isArray((payload as Raw).announcements)
      ? (payload as Raw).announcements as unknown[] : [];
  const out: Announcement[] = [];
  for (const raw of list) {
    if (!raw || typeof raw !== "object") continue;
    const o = raw as Raw;
    const id = str(o.id), title = pick(o, "title", lang);
    const type = o.type === "modal" || o.type === "corner" ? o.type : null;
    if (!id || !title || !type || seen.has(id)) continue;
    const from = Date.parse(str(o.from) || ""), until = Date.parse(str(o.until) || "");
    if ((!isNaN(from) && now < from) || (!isNaN(until) && now > until)) continue;
    const items = Array.isArray(o.items)
      ? (o.items as unknown[]).flatMap((it) => {
          if (!it || typeof it !== "object") return [];
          const r = it as Raw, heading = pick(r, "title", lang);
          return heading ? [{ title: heading, body: pick(r, "body", lang), image: str(r.image) }] : [];
        })
      : undefined;
    out.push({ id, type, tag: pick(o, "tag", lang), tagColor: color(o.tag_color), title, body: pick(o, "body", lang), image: str(o.image),
               cta: pick(o, "cta", lang), url: str(o.url), items, immediate: o.immediate === true });
  }
  return out;
}

// Seen ids live here and on the person, so a flag condition can exclude
// them and a signed-in user never sees a card twice across devices.
const SEEN_KEY = "cycls_seen_announcements";
export function seenAnnouncements(): Set<string> {
  try { return new Set<string>(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]")); } catch { return new Set(); }
}
function markSeen(id: string) {
  const s = seenAnnouncements(); s.add(id);
  try { localStorage.setItem(SEEN_KEY, JSON.stringify([...s].slice(-200))); } catch { /* private mode */ }
  setPerson({ [`announcement_seen/${id}`]: true });
}

type Flags = {
  loaded: boolean;
  push: { on: boolean; immediate?: boolean; snoozeDays?: number };
  announcements: unknown;
};

function useFlags(): Flags {
  const [flags, setFlags] = useState<Flags>({ loaded: false, push: { on: false }, announcements: null });
  useEffect(() => {
    const remote = flagsProvider();
    // No flags provider: the prompt still shows after the first finished turn; there are no announcements to show.
    if (!remote) { setFlags({ loaded: true, push: { on: true }, announcements: null }); return; }
    return remote.on(() => {
      const prompt = remote.get("notification_prompt");
      const o = (prompt.payload && typeof prompt.payload === "object" ? prompt.payload : {}) as Raw;
      const ann = remote.get("announcements");
      setFlags({
        loaded: true,
        push: { on: prompt.enabled, immediate: o.immediate === true,
                snoozeDays: typeof o.snooze_days === "number" ? o.snooze_days : undefined },
        announcements: ann.enabled ? ann.payload : null,
      });
    });
  }, []);
  return flags;
}

const shownOnce = new Set<string>();   // per page load, remounts included

export function Surfaces({ config, ready, active }: { config: AppConfig | null; ready: boolean; active: boolean }) {
  const provider = useMemo(() => { initNotifications(config?.notifications); return pushProvider(); }, [config]);
  const flags = useFlags();
  const lang = getLang();
  const [seen, setSeen] = useState(seenAnnouncements);
  const cards = useMemo(() => parseAnnouncements(flags.announcements, seen, lang), [flags.announcements, seen, lang]);
  const modal = cards.find((c) => c.type === "modal") ?? null;
  // The corner waits for the modal: one thing at a time, never a pile-up.
  const tip = !modal ? cards.find((c) => c.type === "corner" && (ready || c.immediate)) ?? null : null;

  const [pushDone, setPushDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const push = !modal && !tip && !pushDone && !!provider && flags.push.on && (ready || !!flags.push.immediate)
    && pushStatus() === "default" && !promptSnoozed(flags.push.snoozeDays ?? SNOOZE_DAYS);

  // One `shown` per card per page, fired when it is actually on screen.
  const visible = active ? [modal && `a:${modal.id}`, tip && `a:${tip.id}`, push && "push"].filter(Boolean).join("|") : "";
  useEffect(() => {
    for (const key of visible.split("|").filter(Boolean)) {
      if (shownOnce.has(key)) continue;
      shownOnce.add(key);
      if (key === "push") track("notification_prompt_shown", { placement: "corner" });
      else {
        const c = cards.find((x) => `a:${x.id}` === key);
        if (c) track("announcement_shown", { id: c.id, type: c.type });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  if (!active) return null;
  const dir = lang === "ar" ? "rtl" : "ltr";
  // Bottom left in both languages: the canvas and the side panel live on the right.
  const side = "left-4";

  const finish = (c: Announcement, result: "clicked" | "dismissed") => {
    track(`announcement_${result}`, { id: c.id, type: c.type });
    markSeen(c.id);
    setSeen(seenAnnouncements());
    if (result === "clicked" && c.url) window.open(c.url, /^https?:/.test(c.url) ? "_blank" : "_self");
  };
  const answerPush = (result: string) => {
    track("notification_prompt_answered", { placement: "corner", result });
    if (result !== "allowed") snoozePrompt();
    setPushDone(true);
  };

  const closeBtn = (onClick: () => void) => (
    <button onClick={onClick} aria-label={t("dismiss")}
            className="shrink-0 rounded-full p-1 text-muted-foreground/60 transition-colors hover:bg-secondary hover:text-foreground cursor-pointer">
      <Icon name="x" className="size-3.5" />
    </button>
  );
  const primary = "rounded-full bg-foreground px-4 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50 cursor-pointer";

  return (
    <>
      {modal && (
        <>
          <div className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px]" onClick={() => finish(modal, "dismissed")} />
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.15 }}
            dir={dir} role="dialog" aria-modal
            className={cn("fixed left-1/2 top-1/2 z-[80] max-h-[85vh] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-border bg-background shadow-xl",
                          modal.items?.length ? "w-[min(460px,92vw)] overflow-y-auto" : "w-[min(680px,92vw)]")}
          >
            {modal.items?.length ? (
              // A digest: several things, each a row.
              <>
                <div className="flex items-start justify-between gap-3 px-5 pt-4">
                  <div className="min-w-0">
                    {modal.tag && <Tag color={modal.tagColor}>{modal.tag}</Tag>}
                    <h2 className="text-base font-semibold">{modal.title}</h2>
                  </div>
                  {closeBtn(() => finish(modal, "dismissed"))}
                </div>
                {modal.body && <p className="px-5 pt-1 text-sm leading-snug text-muted-foreground">{modal.body}</p>}
                <div className="flex flex-col gap-4 px-5 py-4">
                  {modal.items.map((it, i) => (
                    <div key={i} className="flex items-start gap-3">
                      {it.image && <img src={it.image} alt="" className="size-14 shrink-0 rounded-lg object-cover" />}
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{it.title}</p>
                        {it.body && <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{it.body}</p>}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="flex justify-end px-5 pb-4">
                  <button onClick={() => finish(modal, "clicked")} className={primary}>{modal.cta || t("gotIt")}</button>
                </div>
              </>
            ) : (
              // One feature: the words on the start side, the picture on the end side.
              <div className="relative flex flex-col-reverse sm:flex-row">
                <div className="flex flex-1 flex-col justify-center gap-2 p-6 sm:py-8">
                  {modal.tag && <Tag color={modal.tagColor}>{modal.tag}</Tag>}
                  <h2 className="text-lg font-semibold leading-snug">{modal.title}</h2>
                  {modal.body && <p className="text-sm leading-snug text-muted-foreground">{modal.body}</p>}
                  <div className="mt-3">
                    <button onClick={() => finish(modal, "clicked")} className={primary}>{modal.cta || t("gotIt")}</button>
                  </div>
                </div>
                {modal.image && (
                  <img src={modal.image} alt="" className="h-44 w-full shrink-0 object-cover sm:h-auto sm:w-[280px]" />
                )}
                <span className="absolute end-3 top-3 rounded-full bg-background/70 backdrop-blur-sm">
                  {closeBtn(() => finish(modal, "dismissed"))}
                </span>
              </div>
            )}
          </motion.div>
        </>
      )}

      {tip && (
        <motion.div
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
          dir={dir}
          className={cn("fixed bottom-4 z-[60] w-[min(288px,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-border bg-background shadow-xl", side)}
        >
          {tip.image && <img src={tip.image} alt="" className="aspect-[2/1] w-full object-cover" />}
          <div className="p-4">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                {tip.tag && <Tag color={tip.tagColor}>{tip.tag}</Tag>}
                <p className="text-sm font-medium">{tip.title}</p>
              </div>
              {closeBtn(() => finish(tip, "dismissed"))}
            </div>
            {tip.body && <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{tip.body}</p>}
            {tip.cta && (
              <button onClick={() => finish(tip, "clicked")} className={cn(primary, "mt-3 px-3 text-xs")}>{tip.cta}</button>
            )}
          </div>
        </motion.div>
      )}

      {push && (
        <motion.div
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
          dir={dir}
          className={cn("fixed bottom-4 z-[60] w-[min(360px,calc(100vw-2rem))] rounded-2xl border border-border bg-background p-4 shadow-xl", side)}
        >
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary">
              <Bell className="size-4.5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t("notifyTitle")}</p>
              <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{t("notifyBody")}</p>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-end gap-1.5">
            <button onClick={() => answerPush("dismissed")}
                    className="rounded-full px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground cursor-pointer">
              {t("notNow")}
            </button>
            <button disabled={busy} className={primary}
                    onClick={async () => { setBusy(true); answerPush(answerResult(await requestPush())); setBusy(false); }}>
              {t("allow")}
            </button>
          </div>
        </motion.div>
      )}
    </>
  );
}

function Tag({ children, color }: { children: string; color?: string }) {
  return (
    <span
      style={color ? { backgroundColor: color, color: onColor(color) } : undefined}
      className="mb-1.5 inline-block w-fit rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
    >
      {children}
    </span>
  );
}

function Bell({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}
