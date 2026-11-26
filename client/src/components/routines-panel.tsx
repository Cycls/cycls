// Routines (docs/rfc-routines.md): the tab's list and ideas, a routine's page with its runs, the screen a new one starts
// from, and the dialog that changes one. The agent makes every routine; here they are seen, paused, run and changed.
import { useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, isIcon } from "./icon";
import { Instruction, RoutineIcon, RoutinesContext, Works, timeText, uiDir, whenText, type Routine, type When } from "./routine-card";
import { ConnectorIcon, connectorLabel, type Connector } from "./connectors-dialog";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";

export type Example = { name: string; name_ar?: string; prompt: string; prompt_ar?: string; icon?: string };

const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const ar = () => getLang() === "ar";
const said = (e: Example) => ({ name: (ar() && e.name_ar) || e.name, prompt: (ar() && e.prompt_ar) || e.prompt });

// An example's face: the logo of the connector it names, else one of the app's icons.
function ExampleIcon({ icon, connectors, className = "size-9" }: { icon?: string; connectors?: Connector[]; className?: string }) {
  const c = icon ? connectors?.find((x) => x.name === icon) : undefined;
  if (c) return <ConnectorIcon c={c} className={className} />;
  return (
    <span className={cn("flex shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground", className)}>
      <Icon name={icon && isIcon(icon) ? icon : "clock"} className="size-[50%]" />
    </span>
  );
}

// When it runs next, as a person says it: today or tomorrow at its time, else the day.
function nextText(r: Routine) {
  if (!r.next) return "";
  const at = new Date(r.next);
  const diff = Math.round((new Date(at.toDateString()).getTime() - new Date(new Date().toDateString()).getTime()) / 864e5);
  const day = diff === 0 ? t("todayCap") : diff === 1 ? t("tomorrow") : at.toLocaleDateString(getLang(), { weekday: "short", day: "numeric", month: "short" });
  return t("nextRun").replace("{when}", `${day} ${timeText(r.when.time)}`);
}

export function RoutinesPanel({ routines, examples, onNew, onUse, onOpenChat }: {
  routines: Routine[] | null;
  examples?: Example[];
  onNew: () => void;
  onUse: (prompt: string) => void;
  onOpenChat: (id: string) => void;
}) {
  const { connectors } = useContext(RoutinesContext);
  const [open, setOpen] = useState<string | null>(null);
  const r = routines?.find((x) => x.id === open);
  if (r) return <RoutinePage r={r} onBack={() => setOpen(null)} onOpenChat={onOpenChat} />;
  const row = "flex w-full cursor-pointer gap-3 px-4 py-2.5 text-start transition-colors hover:bg-secondary/60";
  const ideas = routines?.length === 0 && !!examples?.length;   // ideas until the first routine is made
  return (
    <div dir={uiDir()} className="flex min-h-0 flex-1 flex-col overflow-y-auto pb-20">
      <button onClick={onNew} className="m-3 flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-border py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary/60">
        <Icon name="plus" className="size-4" />{t("newRoutine")}
      </button>
      {routines?.map((x) => (
        <button key={x.id} onClick={() => setOpen(x.id)} className={cn(row, "items-center")}>
          <RoutineIcon className={cn("size-9", !x.on && "opacity-50")} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-foreground"><bdi>{x.name}</bdi></span>
            <span className="block truncate text-xs text-muted-foreground">{x.on ? whenText(x.when) : t("routinePausedShort")}</span>
          </span>
        </button>
      ))}
      {ideas && <p className="px-4 pb-1 pt-5 text-xs font-medium text-muted-foreground">{t("routineIdeas")}</p>}
      {ideas && examples.map((e) => {
        const { name, prompt } = said(e);
        return (
          <button key={e.name} onClick={() => onUse(prompt)} className={cn(row, "items-start")}>
            <ExampleIcon icon={e.icon} connectors={connectors} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-foreground">{name}</span>
              <span className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{prompt}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// Everything about one routine: its switch, Run now, Edit and Delete, what it is, and its runs, each opening its chat.
function RoutinePage({ r, onBack, onOpenChat }: { r: Routine; onBack: () => void; onOpenChat: (id: string) => void }) {
  const { connectors, save, remove, now, edit, open, connect } = useContext(RoutinesContext);
  const [menu, setMenu] = useState<"open" | "delete" | null>(null);
  const item = "flex w-full cursor-pointer items-center px-3 py-2 text-start text-sm hover:bg-secondary/60";
  const status = r.on ? nextText(r) : t("routinePausedShort");
  return (
    <div dir={uiDir()} className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-2 py-2">
        <button onClick={onBack} aria-label={t("back")} className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary/80 hover:text-foreground">
          <Icon name="chevron-left" className="size-4 rtl:rotate-180" />
        </button>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground"><bdi>{r.name}</bdi></p>
        <button role="switch" aria-checked={!!r.on} aria-label={t(r.on ? "routineOn" : "routinePausedShort")} onClick={() => void save(r.id, { on: !r.on })}
                className={`relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors ${r.on ? "bg-[#3171F6]" : "bg-secondary"}`}>
          <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-all ${r.on ? "start-[18px]" : "start-0.5"}`} />
        </button>
        <div className="relative">
          <button onClick={() => setMenu(menu ? null : "open")} aria-label={t("more")} className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary/80 hover:text-foreground">⋯</button>
          {menu && (
            <div className="absolute end-0 top-9 z-10 w-44 overflow-hidden rounded-lg border border-border bg-background py-1 shadow-lg">
              {menu === "open" ? (
                <>
                  <button className={item} onClick={() => { setMenu(null); void now(r.id); }}>{t("runNow")}</button>
                  <button className={item} onClick={() => { setMenu(null); edit(r, (changed) => save(r.id, changed)); }}>{t("edit")}</button>
                  <button className={`${item} text-red-600`} onClick={() => setMenu("delete")}>{t("delete")}</button>
                </>
              ) : (
                <>
                  <p className="px-3 py-2 text-xs text-muted-foreground">{t("deleteRoutineAsk").replace("{name}", r.name)}</p>
                  <button className={`${item} text-red-600`} onClick={() => { setMenu(null); void remove(r.id).then(onBack); }}>{t("delete")}</button>
                  <button className={item} onClick={() => setMenu(null)}>{t("cancel")}</button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto pb-20">
        <div className="space-y-3 border-b border-border p-4">
          <div className="flex items-center gap-3">
            <RoutineIcon className="size-10" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-foreground">{whenText(r.when)}</p>
              <p className="text-xs text-muted-foreground">{[status, t(r.fresh === false ? "runsInThisChat" : "newChatEachRun")].filter(Boolean).join(" · ")}</p>
            </div>
          </div>
          <Instruction text={r.prompt} />
          {!!(r.connectors?.length || r.files?.length) && <div className="flex flex-wrap gap-2"><Works r={r} connectors={connectors} open={open} connect={connect} /></div>}
        </div>
        <p className="px-4 pb-1 pt-3 text-xs font-medium text-muted-foreground">{t("runs")}</p>
        {!r.runs?.length && <p className="px-4 py-2 text-xs text-muted-foreground">{t("noRunsYet")}</p>}
        {r.runs?.map((run, i) => (
          <button key={`${run.chat}-${i}`} onClick={() => onOpenChat(run.chat)} className="flex w-full cursor-pointer items-center gap-3 px-4 py-2 text-start hover:bg-secondary/60">
            <span className={cn("size-2 shrink-0 rounded-full", run.ok === false ? "bg-red-500" : !run.ok ? "bg-amber-400" : run.said ? "bg-[#3171F6]" : "bg-muted-foreground/40")} />
            <span className="min-w-0 flex-1">
              <span className={cn("block truncate text-[13px]", run.ok === false ? "text-red-600" : "text-foreground")}>
                <bdi>{run.ok === false ? t("couldNotRun") : run.said || (run.ok ? t("nothingNew") : t("running"))}</bdi>
              </span>
              <span className="block text-[11px] text-muted-foreground">
                {new Date(run.at).toLocaleString(getLang(), { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}
              </span>
            </span>
            <Icon name="chevron-right" className="size-3.5 shrink-0 text-muted-foreground rtl:rotate-180" />
          </button>
        ))}
      </div>
    </div>
  );
}

// The screen "+ New routine" opens in the middle: the message box to describe one, and under it the agent's ideas,
// each putting its words in the box.
export function RoutinesStart({ name, examples, connectors, onUse, children }: {
  name?: string; examples: Example[]; connectors?: Connector[]; onUse: (prompt: string) => void; children: ReactNode;
}) {
  return (
    <div dir={uiDir()} className="flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-6 pb-16 pt-16 sm:pt-24">
        <RoutineIcon className="mb-3 size-12 rounded-2xl" />
        <h1 className="font-display text-2xl font-semibold text-foreground">{t("scheduleRoutine")}</h1>
        <p className="mt-1 text-center text-sm text-muted-foreground">{t("routineLead").replace("{name}", name || "")}</p>
        <div className="mt-8 w-full">{children}</div>
        <div className="mt-8 grid w-full gap-2.5 sm:grid-cols-2">
          {examples.map((e) => {
            const { name: title, prompt } = said(e);
            return (
              <button key={e.name} onClick={() => onUse(prompt)} className="flex cursor-pointer items-start gap-3 rounded-2xl border border-border bg-background p-3.5 text-start transition-colors hover:bg-secondary/40">
                <ExampleIcon icon={e.icon} connectors={connectors} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-foreground">{title}</span>
                  <span className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{prompt}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// The dialog the pencil and Edit open: its name and instruction, what it works with (+ adds a connected one), when,
// and whether each run starts a new chat. On a phone it fills the screen.
export function RoutineDialog({ routine, connectors, onSave, onClose }: {
  routine: Routine;
  connectors?: Connector[];
  onSave: (r: Routine) => Promise<void> | void;
  onClose: () => void;
}) {
  const [r, setR] = useState<Routine>(routine);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const when = (patch: Partial<When>) => setR({ ...r, when: { ...r.when, ...patch } });
  const times = [...new Set([...Array.from({ length: 48 }, (_, i) => `${String(i >> 1).padStart(2, "0")}:${i % 2 ? "30" : "00"}`), r.when.time])].sort();
  const connected = (connectors || []).filter((c) => c.connected);
  const field = "rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm text-foreground";
  const row = "flex items-center justify-between gap-3 py-2.5 text-sm";
  return createPortal(
    <div dir={uiDir()}>
      <div className="fixed inset-0 z-[80] bg-black/40" onClick={onClose} />
      <div className="fixed inset-0 z-[80] flex flex-col overflow-y-auto bg-card p-5 sm:inset-auto sm:left-1/2 sm:top-1/2 sm:max-h-[88vh] sm:w-[min(600px,94vw)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl sm:border sm:border-border sm:shadow-xl">
        <div className="mb-4 flex items-center gap-3">
          <RoutineIcon className="size-9" />
          <input dir="auto" value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} aria-label={t("name")}
                 className="min-w-0 flex-1 bg-transparent text-start font-display text-lg font-semibold text-foreground outline-none" />
          <button onClick={onClose} aria-label={t("cancel")} className="cursor-pointer rounded-lg p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"><Icon name="x" className="size-5" /></button>
        </div>
        <div className="rounded-2xl border border-border bg-background p-3">
          <textarea dir="auto" value={r.prompt} onChange={(e) => setR({ ...r, prompt: e.target.value })} rows={6}
                    className="w-full resize-none bg-transparent text-sm leading-relaxed text-foreground outline-none" />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Works r={r} connectors={connectors} drop={(kind, v) => setR({ ...r, [kind]: (r[kind] || []).filter((x) => x !== v) })} />
            {connected.length > 0 && (
              <div className="relative">
                <button onClick={() => setAdding(!adding)} className="flex cursor-pointer items-center gap-1.5 rounded-xl border border-dashed border-border px-3 py-2 text-[13px] text-muted-foreground hover:bg-secondary hover:text-foreground">
                  <Icon name="plus" className="size-3.5" />{t("add")}
                </button>
                {adding && (
                  <div className="absolute start-0 top-11 z-10 max-h-64 w-60 overflow-y-auto rounded-xl border border-border bg-background py-1 shadow-lg">
                    {connected.map((c) => {
                      const on = (r.connectors || []).includes(c.name);
                      return (
                        <button key={c.name} onClick={() => setR({ ...r, connectors: on ? r.connectors!.filter((x) => x !== c.name) : [...(r.connectors || []), c.name] })}
                                className="flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-sm text-foreground hover:bg-secondary/60">
                          <ConnectorIcon c={c} className="size-6 rounded-lg" />
                          <span className="min-w-0 flex-1 truncate text-start">{connectorLabel(c)}</span>
                          {on && <Icon name="check" className="size-4 text-[#3171F6]" />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="mt-3 divide-y divide-border">
          <div className={row}>
            <span>{t("whenLabel")}</span>
            <span className="flex items-center gap-2">
              <select value={r.when.every} onChange={(e) => when({ every: e.target.value as When["every"] })} className={field}>
                {(["day", "days", "month", "once"] as const).map((k) => <option key={k} value={k}>{t(`every_${k}`)}</option>)}
              </select>
              <select value={r.when.time} onChange={(e) => when({ time: e.target.value })} className={field}>
                {times.map((x) => <option key={x} value={x}>{timeText(x)}</option>)}
              </select>
            </span>
          </div>
          {r.when.every === "days" && (
            <div className="flex flex-wrap gap-1.5 py-2.5">
              {DAYS.map((d, i) => {
                const on = r.when.days?.includes(d);
                return (
                  <button key={d} onClick={() => when({ days: on ? r.when.days!.filter((x) => x !== d) : DAYS.filter((x) => x === d || r.when.days?.includes(x)) })}
                          className={`cursor-pointer rounded-full px-3 py-1 text-xs ${on ? "bg-foreground text-background" : "bg-secondary text-foreground"}`}>
                    {new Date(2026, 0, 4 + i).toLocaleDateString(getLang(), { weekday: "short" })}
                  </button>
                );
              })}
            </div>
          )}
          {r.when.every === "month" && (
            <div className={row}><span>{t("dayOfMonth")}</span>
              <input type="number" min={1} max={31} value={r.when.day ?? 1} onChange={(e) => when({ day: Number(e.target.value) })} className={`${field} w-20`} />
            </div>
          )}
          {r.when.every === "once" && (
            <div className={row}><span>{t("dateLabel")}</span>
              <input type="date" value={r.when.date ?? ""} onChange={(e) => when({ date: e.target.value })} className={field} />
            </div>
          )}
          <div className={row}><span>{t("whoHears")}</span><span className="text-muted-foreground">{t("you")}</span></div>
          <div className={row}>
            <span>{t("newChatEachRun")}</span>
            <button role="switch" aria-checked={r.fresh !== false} onClick={() => setR({ ...r, fresh: r.fresh === false })}
                    className={`relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors ${r.fresh !== false ? "bg-[#3171F6]" : "bg-secondary"}`}>
              <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-all ${r.fresh !== false ? "start-[18px]" : "start-0.5"}`} />
            </button>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="cursor-pointer rounded-full px-4 py-2 text-sm text-muted-foreground hover:bg-secondary">{t("cancel")}</button>
          <button disabled={busy || !r.name.trim() || !r.prompt.trim()} onClick={async () => { setBusy(true); try { await onSave(r); onClose(); } finally { setBusy(false); } }}
                  className="cursor-pointer rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-80 disabled:opacity-50">
            {t("save")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
