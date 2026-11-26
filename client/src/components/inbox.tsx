import { useEffect, useState } from "react";
import { Icon } from "./icon";
import { Face } from "./file-details";
import { Popover } from "./popover";
import { t, timeAgo } from "../lib/i18n";
import type { InboxItem } from "../hooks/use-inbox";

// A task that ended while its owner was away: how it ended.
const AWAY: Record<string, Parameters<typeof t>[0]> = { done: "awayDone", asks: "awayAsks", approve: "awayApprove", failed: "awayFailed" };

// The bell, beside search: what concerns the person in every workspace they are in, newest first. Opening it reads
// everything in it; an item opens its chat, in its own workspace. The count rides in the tab's title too.
export function InboxBell({ inbox, workspaces, here, onOpen }: {
  inbox: { items: InboxItem[]; unread: number; open: () => Promise<void> };
  workspaces?: { id: string; name: string; icon?: string }[];
  here?: string;
  onOpen: (item: InboxItem) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const plain = document.title.replace(/^\(\d+\+?\) /, "");
    document.title = inbox.unread ? `(${inbox.unread > 99 ? "99+" : inbox.unread}) ${plain}` : plain;
  }, [inbox.unread]);
  const where = (ws?: string) => {
    const w = ws && ws !== here ? workspaces?.find((x) => x.id === ws) : undefined;
    return w ? [w.icon, w.name].filter(Boolean).join(" ") : "";
  };
  const said = (i: InboxItem) => {
    if (i.kind === "away") return t(AWAY[i.state ?? "done"] ?? "awayDone");
    if (i.kind === "routine")   // a routine's: its name, what it told below; or that it could not run, or is paused
      return i.state ? t(i.state === "paused" ? "routinePaused" : "routineStuck").replace("{name}", i.title || "")
        : <span className="font-medium">{i.title}</span>;
    const [before, after = ""] = t(i.kind === "reply" ? "repliedToYou" : "mentionedYou").split("{name}");
    return <>{before}<span className="font-medium">{i.by?.name || t("someone")}</span>{after}</>;
  };
  return (
    <>
      <button
        onClick={() => { setOpen(true); void inbox.open().catch(() => {}); }}
        aria-label={t("notifications")}
        className="relative cursor-pointer rounded-lg p-2 text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground"
      >
        <Icon name="bell" className="size-4.5" />
        {inbox.unread > 0 && (
          <span className="absolute end-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#3171F6] px-1 text-[10px] font-semibold text-white">
            {inbox.unread > 9 ? "9+" : inbox.unread}
          </span>
        )}
      </button>
      <Popover open={open} onClose={() => setOpen(false)}
               className="right-2 top-13.5 mt-2 max-h-[70vh] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border border-border bg-background py-1 shadow-lg">
        <div className="px-4 pb-1.5 pt-2.5 text-sm font-semibold">{t("notifications")}</div>
        {!inbox.items.length && <p className="px-4 pb-4 pt-1 text-sm text-muted-foreground">{t("inboxEmpty")}</p>}
        {inbox.items.map((i) => (
          <button key={i.id} onClick={() => { setOpen(false); onOpen(i); }}
                  className="flex w-full cursor-pointer items-start gap-3 px-4 py-2.5 text-start transition-colors hover:bg-secondary/60">
            {i.by ? <Face c={{ by: i.by, at: i.at }} size={32} />
              : <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground"><Icon name={i.kind === "routine" ? "clock" : "chat"} className="size-4" /></span>}
            <span className="min-w-0 flex-1">
              <span className="block text-sm text-foreground">{said(i)}</span>
              {i.text && <span dir="auto" className="mt-0.5 line-clamp-2 text-xs text-muted-foreground [overflow-wrap:anywhere]">{i.text.replace(/\(?https?:\/\/\S+/g, "").trim()}</span>}
              <span dir="auto" className="mt-0.5 block truncate text-[11px] text-muted-foreground/80">
                {[i.kind !== "routine" && i.title, where(i.ws), timeAgo(i.at)].filter(Boolean).join(" · ")}
              </span>
            </span>
          </button>
        ))}
      </Popover>
    </>
  );
}
