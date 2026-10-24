// The question a gated call asks, in the conversation where the agent asked it. It asks about the action as
// a colleague would, wears the face of the step it stands for (a connector's logo, a file's tile, a tool's
// glyph, the trash for a delete) and, once answered, stays as a one-line receipt.
import { createContext, useContext, useState } from "react";
import { Icon, Spinner } from "./icon";
import { Star } from "./cycls-star";
import { GLYPHS } from "./parts/step-part";
import { ConnectorsContext } from "./parts/tool-call";
import { ConnectorIcon, L, connectorLabel, type CardAction, type Connector } from "./connectors-dialog";
import { ext, tintTile, tintLabel } from "./canvas-utils";
import { cn } from "../lib/utils";
import { t } from "../lib/i18n";
import type { Part } from "../hooks/use-chat";

export type Confirm = {
  tool: string; key: string; label: string; args?: Record<string, unknown>; connector?: string;
  tool_name?: string; step?: string; risk?: string; id?: string;
};
// `yes` approves, else "Not now"; `remember` is "Don't ask again", which is Always allow for that tool.
export type Answer = (card: Confirm, yes: boolean, remember: boolean, title: string) => void;
// `busy` while a run is going: an approved card shows it working until the call is made again.
export const ApprovalContext = createContext<{ agent: string; answer?: Answer; busy?: boolean }>({ agent: "" });

type Words = { title: string; sub?: string; button: string; done: string; rows: [string, string][];
               cmd?: string; details?: string; remember?: string };

const fill = (s: string, vars: Record<string, string>) => s.replace(/\{(\w+)\}/g, (m, k) => vars[k] ?? m);
const at = (o: unknown, path: string) =>
  path.split(".").reduce<unknown>((v, k) => (v && typeof v === "object" ? (v as Record<string, unknown>)[k] : undefined), o);

// A detail as a person reads it: a string as it is, anything else as the strings inside it (Graph's recipients).
export function shown(v: unknown): string {
  const out: string[] = [];
  const walk = (x: unknown) => {
    if (typeof x === "string" || typeof x === "number") out.push(String(x));
    else if (x && typeof x === "object") Object.values(x).forEach(walk);
  };
  walk(v);
  return [...new Set(out)].join(", ");
}

// The CMS action a call matches: "POST me/sendMail" against a REST call's method and path, a tool's name otherwise.
export function matchAction(card: Confirm, actions: CardAction[] = []): CardAction | undefined {
  const args = card.args || {};
  if (!card.tool.endsWith("_request")) return actions.find((a) => a.match === card.tool || card.tool.endsWith(`_${a.match}`));
  const method = String(args.method || "GET").toUpperCase();
  const path = String(args.path || "").split("?")[0].replace(/^\//, "");
  return actions.find((a) => {
    const [m, p = ""] = a.match.trim().split(/\s+/);
    const glob = p.replace(/^\//, "").split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join("[^/]+");
    return m.toUpperCase() === method && new RegExp(`^${glob}$`, "i").test(path);
  });
}

export function words(card: Confirm, c: Connector | undefined, agent: string): Words {
  const args = card.args || {};
  const danger = card.risk === "destructive";
  const vars: Record<string, string> = { agent, connector: c ? connectorLabel(c) : card.connector || "" };
  const s = (k: Parameters<typeof t>[0]) => fill(t(k), vars);
  const raw = JSON.stringify(args, null, 2);
  if (card.connector) {
    const a = matchAction(card, c?.actions);
    let body: unknown;
    try { body = typeof args.body === "string" ? JSON.parse(args.body) : args.body; } catch { body = undefined; }
    const rows = (a?.show || []).map(({ id, label, from }): [string, string] => {
      const v = shown(at(args, from) ?? at(body, from.replace(/^body\./, "")));
      if (id) vars[id] = v;
      return [L(label), v];
    }).filter(([, v]) => v);
    const say = typeof args.context === "string" ? args.context : card.step || "";   // the agent's own line on the call
    const own = (x?: Parameters<typeof L>[0]) => (x ? fill(L(x), vars) : "");
    return {
      title: a ? own(a.ask) : s(danger ? "cardAskConnectorDelete" : "cardAskConnector"),
      sub: (a && own(a.who)) || (danger ? s("cardCantUndo") : say),
      button: (a && own(a.button)) || s(danger ? "cardDelete" : "cardAllow"),
      done: (a && own(a.done)) || s("cardDone"), rows, details: raw,
      remember: danger ? undefined : s(card.tool.endsWith("_request") ? "cardRememberConnector" : "cardRememberAction"),
    };
  }
  switch (card.tool) {
    case "bash":
      return { title: s(danger ? "cardAskDeleteRun" : "cardAskRun"), sub: s(danger ? "cardCantUndo" : "cardRunSub"),
               button: s(danger ? "cardDelete" : "cardRunIt"), done: s(danger ? "cardDeleted" : "cardRan"),
               rows: [], cmd: String(args.command || ""), remember: danger ? undefined : s("cardRememberCommands") };
    case "edit": {
      vars.file = String(args.path || "").split("/").pop() || "";
      const change = args.old_str != null ? `- ${args.old_str}\n+ ${args.new_str ?? ""}` : String(args.file_text ?? args.new_str ?? "");
      return { title: s("cardAskEdit"), sub: s("cardEditSub"), button: s("cardApply"), done: s("cardEdited"),
               rows: [[s("cardFile"), String(args.path || "")]], details: change, remember: s("cardRememberEdits") };
    }
    case "database":
      vars.key = String(args.key || "");
      return danger
        ? { title: s("cardAskForget"), sub: s("cardCantUndo"), button: s("cardForget"), done: s("cardForgotten"), rows: [[s("cardWhat"), vars.key]] }
        : { title: s("cardAskSave"), sub: s("cardSaveSub"), button: s("cardSave"), done: s("cardSaved"), rows: [[s("cardWhat"), vars.key]],
            remember: s("cardRememberSaves") };
    case "build_app":
      vars.app = String(args.name || args.slug || "");
      return { title: s("cardAskBuild"), sub: s("cardBuildSub"), button: s("cardBuild"), done: s("cardBuilt"), rows: [],
               remember: s("cardRememberBuilds") };
    case "skill":
      vars.skill = String(args.name || "");
      return { title: s("cardAskPublish"), sub: s("cardPublishSub"), button: s("cardPublish"), done: s("cardPublished"), rows: [],
               remember: s("cardRememberPublish") };
  }
  return { title: s("cardAskOther"), sub: card.step, button: s(danger ? "cardDelete" : "cardAllow"), done: s("cardDone"),
           rows: [], details: raw, remember: danger ? undefined : s("cardRememberOther") };
}

// The face of the step this card stands for: the trash for a delete, a connector's logo, a file's tile, a tool's glyph.
function Face({ card, c }: { card: Confirm; c?: Connector }) {
  const tile = "flex size-9 shrink-0 items-center justify-center rounded-xl";
  if (card.risk === "destructive") return <span className={cn(tile, "bg-destructive/10 text-destructive")}><Icon name="trash" strokeWidth={1.5} className="size-[18px]" /></span>;
  if (c) return <ConnectorIcon c={c} />;
  const file = card.tool === "edit" ? String(card.args?.path || "") : "";
  if (file) return <span className={cn(tile, "bg-secondary text-[10px] font-semibold uppercase text-muted-foreground")} style={{ ...tintTile(file), ...tintLabel(file) }}>{ext(file).slice(0, 3)}</span>;
  const glyph = card.tool_name && GLYPHS[card.tool_name];
  return (
    <span className={cn(tile, "bg-secondary text-muted-foreground")}>
      {glyph ? <Icon name={glyph} strokeWidth={1.25} className="size-[18px]" /> : <Star hollow size={18} />}
    </span>
  );
}

export function ApprovalCard({ part }: { part: Part }) {
  const card = part.card as unknown as Confirm;
  const { agent, answer, busy } = useContext(ApprovalContext);
  const c = useContext(ConnectorsContext).find((x) => x.name === card.connector);
  const [remember, setRemember] = useState(false);
  const w = words(card, c, agent);
  const state = part.state || "waiting";

  if (state !== "waiting" || !answer) {   // a shared chat has nobody to answer: it shows the question as a receipt
    const [icon, text, tone] =
      state === "waiting" ? [<Icon name="hand" className="size-4" />, t("cardWaiting"), "text-muted-foreground"]
      : state === "approved" ? (busy ? [<Spinner className="size-4" />, t("cardWorking"), "text-muted-foreground"]
                                   : [<Icon name="check" className="size-4" />, t("cardApproved"), "text-foreground"])
      : state === "done" ? [<Icon name="check" className="size-4" />, w.done, "text-foreground"]
      : state === "failed" ? [<Icon name="x" className="size-4" />, t("cardFailed"), "text-destructive"]
      : [<Icon name="x" className="size-4" />, t(state === "declined" ? "cardDeclined" : "cardSkipped"), "text-muted-foreground"];
    return (
      <div className={cn("my-1 flex items-center gap-2 text-sm", tone)}>
        {icon}<span dir="auto" className="min-w-0 truncate">{text}</span>
        {!["done", "approved"].includes(state) && <span dir="auto" className="min-w-0 truncate text-muted-foreground">· {w.title}</span>}
        {part.remembered && <span className="shrink-0 text-xs text-muted-foreground">· {t("cardWontAsk")}</span>}
      </div>
    );
  }

  const danger = card.risk === "destructive";
  return (
    <div className={cn("my-1 flex flex-col gap-3 rounded-2xl border bg-background p-4 shadow-sm",
                       danger ? "border-destructive/30" : "border-border")}>
      <div className="flex items-start gap-3">
        <Face card={card} c={c} />
        <div className="min-w-0">
          <p dir="auto" className="text-[15px] font-semibold leading-snug text-foreground">{w.title}</p>
          {w.sub && <p dir="auto" className={cn("text-[13px] leading-snug", danger ? "text-destructive" : "text-muted-foreground")}>{w.sub}</p>}
        </div>
      </div>
      {w.rows.length > 0 && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3.5 gap-y-1 rounded-xl bg-secondary/60 px-3 py-2.5 text-[13px]">
          {w.rows.map(([k, v]) => [
            <dt key={`k${k}`} className="text-muted-foreground">{k}</dt>,
            <dd key={`v${k}`} dir="auto" className="min-w-0 break-words text-foreground">{v}</dd>,
          ])}
        </dl>
      )}
      {w.cmd && <pre dir="ltr" className="overflow-x-auto rounded-xl bg-secondary/60 px-3 py-2.5 font-mono text-[12px] text-foreground">{w.cmd}</pre>}
      {w.details && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-muted-foreground">{t("cardDetails")}</summary>
          <pre dir="ltr" className="mt-2 max-h-60 overflow-auto rounded-xl bg-secondary/60 px-3 py-2.5 font-mono text-[12px] text-muted-foreground">{w.details}</pre>
        </details>
      )}
      {w.remember && (
        <label className="flex cursor-pointer items-start gap-2.5 text-[13px] text-foreground">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="mt-0.5 size-4 accent-foreground" />
          <span dir="auto">{w.remember}<span className="block text-xs text-muted-foreground">{t("cardRememberHint")}</span></span>
        </label>
      )}
      <div className="flex justify-end gap-2">
        <button onClick={() => answer?.(card, false, false, w.title)}
                className="cursor-pointer rounded-full px-4 py-2 text-[13px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
          {t("cardNotNow")}
        </button>
        <button onClick={() => answer?.(card, true, remember, w.title)}
                className={cn("cursor-pointer rounded-full px-4 py-2 text-[13px] font-medium transition hover:opacity-85",
                              danger ? "bg-destructive text-white" : "bg-foreground text-background")}>
          {w.button}
        </button>
      </div>
    </div>
  );
}
