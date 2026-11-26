// A routine the agent proposes, in its message (docs/rfc-routines.md): nothing is made before the person presses Set
// up; then the card is the routine's, with Run now. A change asks for Save, a delete asks once.
import { createContext, useContext, useState } from "react";
import { Icon } from "./icon";
import { ConnectorIcon, connectorLabel, type Connector } from "./connectors-dialog";
import { TypeTile } from "./example-filters";
import { tileExt } from "./canvas-utils";
import { t, getLang } from "../lib/i18n";
import { askPush } from "../lib/notifications";
import { cn } from "../lib/utils";

export type When = { every: "once" | "day" | "days" | "month"; days?: string[]; day?: number; date?: string; time: string; tz: string };
export type Routine = {
  id: string; name: string; prompt: string; when: When; fresh?: boolean; connectors?: string[]; files?: string[];
  chat?: string | null; on?: boolean; next?: string | null; runs?: { at: string; chat: string; said?: string; ok?: boolean }[];
};

export const RoutinesContext = createContext<{
  routines: Routine[] | null;
  connectors?: Connector[];
  make: (r: Routine) => Promise<void>;
  save: (id: string, patch: Partial<Routine>) => Promise<void>;
  remove: (id: string) => Promise<void>;
  now: (id: string) => Promise<void>;
  edit: (r: Routine, onSave: (r: Routine) => Promise<void> | void) => void;   // the dialog, on this routine
  open?: (path: string) => void;   // a file it works with, in the canvas
  connect?: (name: string) => void;   // a connector it needs, signed in to from its card
}>({ routines: null, make: async () => {}, save: async () => {}, remove: async () => {}, now: async () => {}, edit: () => {} });

// The chat and the side panel are laid out left to right; what is routines' follows the reader's language.
export const uiDir = () => (getLang() === "ar" ? "rtl" : "ltr");

const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
export const timeText = (time: string) => {
  const [h, m] = time.split(":").map(Number);
  return new Date(2026, 0, 4, h, m).toLocaleTimeString(getLang(), { hour: "numeric", minute: "2-digit" });
};

// "Every day · 8:00 AM", in the person's language; the days as their locale names them.
export function whenText(w: When) {
  const lang = getLang();
  const day = (d: string) => new Date(2026, 0, 4 + DAYS.indexOf(d)).toLocaleDateString(lang, { weekday: "short" });   // 4 Jan 2026 is a Sunday
  const how = w.every === "day" ? t("everyDay")
    : w.every === "days" ? (w.days || []).map(day).join(lang === "ar" ? "، " : ", ")
    : w.every === "month" ? t("everyMonth").replace("{day}", String(w.day ?? 1))
    : w.date ? new Date(`${w.date}T00:00`).toLocaleDateString(lang, { month: "short", day: "numeric" }) : "";
  return `${how} · ${timeText(w.time)}`;
}

export const RoutineIcon = ({ className = "size-9" }: { className?: string }) => (
  <span className={cn("flex shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground", className)}>
    <Icon name="clock" className="size-[52%]" />
  </span>
);

// The instruction each run is given: its first lines, and all of it on a click.
export function Instruction({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const long = text.length > 220 || text.split("\n").length > 3;
  return (
    <div className="rounded-xl bg-secondary/50 px-3.5 py-3">
      <p dir="auto" className={cn("whitespace-pre-line text-[13px] leading-relaxed text-foreground/85", !all && "line-clamp-3")}>{all ? text : text.replace(/\n\s*\n/g, "\n")}</p>
      {long && (
        <button onClick={() => setAll(!all)} className="mt-1.5 cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
          {t(all ? "showLess" : "readMore")}
        </button>
      )}
    </div>
  );
}

// What a routine works with: each connector by its logo, ✓ once connected or Connect until then, and each file by its
// type, opening in the canvas. `drop` gives each a × instead.
export function Works({ r, connectors, drop, open, connect }: {
  r: Pick<Routine, "connectors" | "files">;
  connectors?: Connector[];
  drop?: (kind: "connectors" | "files", value: string) => void;
  open?: (path: string) => void;
  connect?: (name: string) => void;
}) {
  const chip = "flex max-w-full items-center gap-2 rounded-xl border border-border bg-background py-1.5 ps-1.5 pe-3 text-[13px] text-foreground";
  const x = (kind: "connectors" | "files", v: string) => drop && (
    <button onClick={() => drop(kind, v)} aria-label={t("delete")} className="-me-1 cursor-pointer rounded p-0.5 text-muted-foreground hover:text-foreground">
      <Icon name="x" className="size-3" />
    </button>
  );
  return (
    <>
      {(r.connectors || []).map((n) => {
        const known = connectors?.find((o) => o.name === n), c = known ?? ({ name: n } as Connector);
        return (
          <span key={`c:${n}`} className={chip}>
            <ConnectorIcon c={c} className="size-6 rounded-lg" />{connectorLabel(c)}
            {known && !drop && (known.connected
              ? <Icon name="check" className="size-3.5 shrink-0 text-[#3171F6]" />
              : connect && <button onClick={() => connect(n)} className="-me-1 shrink-0 cursor-pointer rounded-full bg-foreground px-2.5 py-0.5 text-[11px] font-medium text-background hover:opacity-80">{t("connectShort")}</button>)}
            {x("connectors", n)}
          </span>
        );
      })}
      {(r.files || []).map((f) => {
        const name = f.split("/").pop() || f;
        const face = <><TypeTile name={name} label={(tileExt(name) || "file").slice(0, 4).toUpperCase()} size={24} /><bdi className="truncate">{name}</bdi></>;
        return open && !drop
          ? <button key={`f:${f}`} title={f} onClick={() => open(f)} className={cn(chip, "cursor-pointer transition-colors hover:bg-secondary/60")}>{face}</button>
          : <span key={`f:${f}`} title={f} className={chip}>{face}{x("files", f)}</span>;
      })}
    </>
  );
}

export function RoutineCard({ card }: { card: { routine?: Routine; change?: boolean; delete?: boolean } }) {
  const { routines, connectors, make, save, remove, now, edit, open, connect } = useContext(RoutinesContext);
  const [done, setDone] = useState<"cancelled" | "saved" | "deleted" | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(card.routine);   // the pencil changes a proposal before Set up
  const made = routines?.find((x) => x.id === draft?.id);
  const r = card.change || card.delete ? draft : made ?? draft;
  if (!r) return null;
  const go = (f: () => Promise<void>, then?: "saved" | "deleted") => async () => {
    setBusy(true);
    try { await f(); if (then) setDone(then); } finally { setBusy(false); }
  };
  const line = (text: string) => <p dir={uiDir()} className="my-2 text-xs text-muted-foreground">{text}</p>;
  if (done === "cancelled") return line(t("routineNotSetUp"));
  if (done === "deleted" || (card.delete && !made && routines)) return line(t("routineDeleted"));
  const live = !card.change && !card.delete && !!made;
  const setUp = live || done === "saved";
  const button = "cursor-pointer rounded-full px-4 py-1.5 text-[13px] font-medium transition disabled:opacity-50";
  const works = !!(r.connectors?.length || r.files?.length);
  const missing = card.delete ? [] : (r.connectors || []).flatMap((n) => connectors?.filter((c) => c.name === n && !c.connected) ?? []);
  return (
    <div dir={uiDir()} className="my-3 w-full overflow-hidden rounded-2xl border border-border bg-background">
      <div className="flex items-center gap-3 px-4 pt-4">
        <RoutineIcon className="size-10" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold text-foreground"><bdi>{r.name}</bdi></p>
          <p className="mt-0.5 text-xs text-muted-foreground">{whenText(r.when)}</p>
        </div>
        {!card.delete && done !== "saved" && (
          <button onClick={() => edit(r, live ? (c) => save(r.id, c) : setDraft)} aria-label={t("edit")}
                  className="cursor-pointer rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            <Icon name="pencil" className="size-4" />
          </button>
        )}
      </div>
      <div className="space-y-3 px-4 py-3.5">
        <Instruction text={r.prompt} />
        {works && <div className="flex flex-wrap gap-2"><Works r={r} connectors={connectors} open={open} connect={connect} /></div>}
      </div>
      <div className="flex items-center gap-2 border-t border-border px-4 py-2.5">
        {setUp ? (
          <>
            <p className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] font-medium text-foreground">
              <Icon name="check" className="size-4 shrink-0 text-[#3171F6]" />
              <span className="truncate">{t(done === "saved" ? "routineSaved" : "routineSetUp").replace("{name}", r.name)}</span>
            </p>
            <button onClick={go(() => now(r.id))} disabled={busy} className={`${button} border border-border text-foreground hover:bg-secondary`}>{t("runNow")}</button>
          </>
        ) : (
          <>
            <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {card.delete ? "" : missing.length ? t("connectToSetUp").replace("{names}", missing.map(connectorLabel).join(getLang() === "ar" ? "، " : ", "))
                : t(r.fresh === false ? "runsInThisChat" : "newChatEachRun")}
            </p>
            <button onClick={() => setDone("cancelled")} disabled={busy} className={`${button} text-muted-foreground hover:bg-secondary hover:text-foreground`}>{t("cancel")}</button>
            <button disabled={busy || missing.length > 0}
                    onClick={card.delete ? go(() => remove(r.id), "deleted") : card.change ? go(() => save(r.id, r), "saved") : go(async () => { await make(r); askPush("routine"); })}
                    className={`${button} ${card.delete ? "bg-red-600 text-white" : "bg-foreground text-background"} hover:opacity-80`}>
              {t(card.delete ? "delete" : card.change ? "save" : "setUp")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
