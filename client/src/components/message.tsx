import { useRef, useState } from "react";
import type { Attachment, Part, Message, Quote, Source } from "../hooks/use-chat";
import { TextPart } from "./parts/text-part";
import { AgentMark, Face } from "./file-details";
import { ThinkingPart } from "./parts/thinking-part";
import { CodePart } from "./parts/code-part";
import { TablePart } from "./parts/table-part";
import { CalloutPart } from "./parts/callout-part";
import { StepPart } from "./parts/step-part";
import { ApprovalReceipt } from "./approval-card";
import { GlowStar, Star } from "./cycls-star";
import { StepGroup } from "./parts/step-group";
import { AgentsCard } from "./parts/agents-card";
import { FilePart } from "./parts/file-part";
import { Gallery, IMAGE_FILE } from "./parts/gallery";
import { UsageNote, usedUp } from "./usage";
import { SelectionChip } from "./selection-chip";
import { SourcesPart } from "./parts/sources-part";
import { ChartPart } from "./parts/chart-part";
import { AttachmentBody } from "./attachment-body";
import { EmojiPicker } from "./emoji-picker";
import { Icon } from "./icon";
import { cn } from "../lib/utils";
import { calloutText } from "../lib/errors";
import { urlKey } from "./parts/sources-part";
import { useMemo } from "react";
import { getLang, localStep, t } from "../lib/i18n";
import { dirOf } from "../lib/bidi";

function renderPart(part: Part, index: number, isStreaming?: boolean, onRetry?: () => void, onOpenFile?: (path: string) => void, sources?: Map<string, Source>) {
  switch (part.type) {
    case "text":
      return <TextPart key={index} text={part.text || ""} onOpenFile={onOpenFile} sources={sources} />;
    case "thinking":
      return (
        <div key={index} className="mb-2">
          <ThinkingPart thinking={part.thinking || ""} isStreaming={isStreaming} />
        </div>
      );
    case "code":
      return (
        <CodePart key={index} code={part.code || ""} language={part.language} />
      );
    case "table":
      return <TablePart key={index} headers={part.headers} rows={part.rows} />;
    case "callout":
      if (part.code === "cut_off") return null;   // the chat's "Stopped before it finished" line says it, with Continue
      return (
        <CalloutPart
          key={index}
          callout={calloutText(part)}
          style={part.style}
          title={part.title}
          onRetry={part.style === "error" ? onRetry : undefined}
        />
      );
    case "sources":
      return <SourcesPart key={index} sources={part.sources || []} />;
    case "chart":
      return <ChartPart key={index} part={part} />;
    case "card":   // a confirm card's line, where the agent asked; the card itself waits over the message box
      return part.card?.action === "confirm" ? <ApprovalReceipt key={index} part={part} /> : null;
    case "step": {
      const { step, tool_name } = localStep(part);
      return (
        <StepPart
          key={index}
          step={step || ""}
          toolName={tool_name}
          isStreaming={isStreaming}
          args={part.args}
          at={part.at}
          plain={part.plain}
        />
      );
    }
    case "status":
      return (
        <div
          key={index}
          className="text-sm text-muted-foreground italic flex items-center gap-2 py-1"
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          {part.status}
        </div>
      );
    default:
      return null;
  }
}

// Successful canvas calls are deliverables — they render as file cards and
// must never fold into a step group. A picture is shown as itself, beside the
// pictures next to it, and one a tool is still making holds its frame there.
// Thinking folds in with the steps around it: think, call, think, call is one
// stretch of work.
function groupKind(p: Part, live?: boolean) {
  if (p.type === "step" && p.tool_name === "Canvas" && p.step && p.ok !== false) return IMAGE_FILE.test(p.step) ? "media" : "file";
  if (p.type === "image" && p.src) return "media";
  if (p.type === "step" && p.picture && live) return "media";
  if (p.type === "thinking") return "step";
  if (p.type === "step" && p.tool_name === "Agent") return "agents";
  return p.type;
}

function groupParts(parts: Part[], live?: boolean) {
  const groups: { kind: string; items: Part[]; startIndex: number }[] = [];
  for (let i = 0; i < parts.length; i++) {
    const kind = groupKind(parts[i], live);
    const last = groups[groups.length - 1];
    if ((kind === "step" || kind === "media" || kind === "agents") && last?.kind === kind) {
      last.items.push(parts[i]);
    } else {
      groups.push({ kind, items: [parts[i]], startIndex: i });
    }
  }
  return groups;
}

// The people and agent a team chat's messages name: each `@name` painted where it is said.
function Mentioned({ text, names }: { text: string; names: string[] }) {
  const known = names.filter(Boolean).sort((a, b) => b.length - a.length).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!known.length) return <>{text}</>;
  return <>{text.split(new RegExp(`(@(?:${known.join("|")}))`, "gi")).map((p, i) =>
    i % 2 ? <span key={i} className="rounded-md bg-[#3171F6]/15 px-1 py-px font-medium text-[#3171F6]">{p}</span> : p)}</>;
}

export type Team = { agent: string; logo?: string; names: string[]; people: Record<string, string>; me?: string };

export const quoteName = (q: Quote, team?: Team) =>
  !q.by ? team?.agent || "" : q.by === team?.me ? t("you") : team?.people[q.by] || q.name || t("someone");

// The message a quote names, brought into view and lit a moment; one on a page not read yet stays where it is.
function findQuoted(id: string) {
  const el = document.getElementById(`m-${id}`);
  el?.scrollIntoView({ block: "center", behavior: "smooth" });
  el?.animate?.([{ backgroundColor: "rgb(49 113 246 / 0.12)" }, { backgroundColor: "transparent" }], { duration: 1600 });
}

// What a reply answers: whose message and how it began. Above a reply a click finds it; in the message box, × lets it go.
export function Quoted({ name, text, onClick, onClose }: { name: string; text: string; onClick?: () => void; onClose?: () => void }) {
  return (
    <div className="flex max-w-full items-start gap-2 rounded-xl border-s-2 border-[#3171F6] bg-secondary/60 px-3 py-1.5 text-xs">
      <button type="button" disabled={!onClick} onClick={(e) => { e.stopPropagation(); onClick?.(); }}
              className="flex min-w-0 flex-1 flex-col items-start text-start enabled:cursor-pointer">
        <span className="font-medium text-[#3171F6]">{name}</span>
        <span dir="auto" className="line-clamp-2 break-words text-muted-foreground">{text}</span>
      </button>
      {onClose && (
        <button type="button" onClick={(e) => { e.stopPropagation(); onClose(); }} aria-label={t("cancel")} title={t("cancel")}
                className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer"><Icon name="x" className="size-3.5" /></button>
      )}
    </div>
  );
}

type BubbleProps = {
  message: Message;
  team?: Team;   // a team chat's: who its messages can name, and who reacted
  anchor?: string;   // a team chat's: what a reply's quote finds it by
  first?: boolean;   // a team chat's run of one person's messages: the name and time top it, the face ends it
  last?: boolean;
  reactions?: Record<string, string[]>;
  onReact?: (emoji: string) => void;
  onReply?: () => void;
  onRewrite?: (text?: string) => Promise<void>;   // your own team message, said again or (no text) taken back
  isStreaming?: boolean;
  onRetry?: () => void;
  // Only passed for the last assistant message — regenerating an earlier one
  // would mean truncating the transcript back to it, which the API doesn't do.
  onRegenerate?: () => void;
  onOpenFile?: (path: string) => void;
  resolveMedia?: (path: string) => Promise<string>;   // a workspace file → a URL its picture can show from
};

const clock = (at: string | number) => new Date(at).toLocaleTimeString(getLang(), { hour: "numeric", minute: "2-digit" });
const QUICK = ["👍", "❤️", "✅"];   // one click from a message's tools; every other is in the picker
const tool = "hover:bg-secondary text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full transition cursor-pointer";

// Two components, not one with an early return: a slot that turns from a person's message into a reply (a team
// chat's reload, a page put above) must not run a different set of hooks.
export function MessageBubble(props: BubbleProps) {
  return props.message.role === "user" ? <UserBubble {...props} /> : <Reply {...props} />;
}

const Smile = () => (
  <svg className="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01" />
  </svg>
);

// Every emoji, behind a smile: the full picker (search, categories, skin tones), above a message low on the screen.
// `data-open` keeps the tools it sits in showing while it is.
function ReactButton({ onReact }: { onReact: (emoji: string) => void }) {
  const [up, setUp] = useState<boolean | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref} className="relative" data-open={up !== null || undefined}>
      <button type="button" onClick={() => setUp(up === null ? ref.current!.getBoundingClientRect().top > 460 : null)}
              className={tool} aria-label={t("react")} title={t("react")}><Smile /></button>
      {up !== null && <EmojiPicker up={up} align="end" onPick={(e) => { onReact(e); setUp(null); }} onClose={() => setUp(null)} />}
    </div>
  );
}

const ReplyButton = ({ onReply }: { onReply: () => void }) => (
  <button type="button" onClick={onReply} className={tool} aria-label={t("reply")} title={t("reply")}>
    <Icon name="reply" className="w-3.5 h-3.5 rtl:-scale-x-100" />
  </button>
);

// A team chat message's tools, beside it on hover (a tap on a phone): a reaction in one click, every other behind
// the smile, a reply, and on your own an edit and a delete that asks once more.
function Tools({ className = "", shown, onReact, onReply, onEdit, onDelete }: {
  className?: string; shown?: boolean; onReact?: (emoji: string) => void; onReply?: () => void; onEdit?: () => void; onDelete?: () => void;
}) {
  const [sure, setSure] = useState(false);
  return (
    <div onMouseLeave={() => setSure(false)}
         className={`z-20 flex shrink-0 items-center gap-0.5 rounded-full border border-border bg-background p-0.5 shadow-sm has-[[data-open]]:visible ${shown ? "visible" : "invisible group-hover:visible"} ${className}`}>
      {onReact && QUICK.map((e) => (
        <button key={e} type="button" onClick={() => onReact(e)}
                className="flex size-7 items-center justify-center rounded-full text-[15px] transition-transform hover:scale-110 hover:bg-secondary cursor-pointer">{e}</button>
      ))}
      {onReact && <ReactButton onReact={onReact} />}
      {onReply && <ReplyButton onReply={onReply} />}
      {(onEdit || onDelete) && onReact && <span className="mx-0.5 h-4 w-px bg-border" />}
      {onEdit && <button type="button" onClick={onEdit} className={tool} aria-label={t("edit")} title={t("edit")}><Icon name="pencil" className="w-3.5 h-3.5" /></button>}
      {onDelete && (sure
        ? <button type="button" onClick={onDelete} className="flex h-7 items-center rounded-full bg-red-500/10 px-2.5 text-xs font-medium text-red-600 dark:text-red-400 cursor-pointer">{t("delete")}</button>
        : <button type="button" onClick={() => setSure(true)} className={tool} aria-label={t("delete")} title={t("delete")}><Icon name="trash" className="w-3.5 h-3.5" /></button>)}
    </div>
  );
}

// A message's reactions: each with how many and who (yours marked), a click puts yours on or takes it off; the smile
// after them adds another.
function Reactions({ on, team, onReact }: { on?: Record<string, string[]>; team?: Team; onReact?: (emoji: string) => void }) {
  const list = Object.entries(on || {});
  if (!list.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {list.map(([e, who]) => (
        <button key={e} type="button" onClick={() => onReact?.(e)}
                title={who.map((p) => (p === team?.me ? t("you") : team?.people[p] || t("someone"))).join(", ")}
                className={`flex h-6 items-center gap-1 rounded-full border px-2 text-xs transition-colors cursor-pointer ${team?.me && who.includes(team.me) ? "border-sky-500/50 bg-sky-500/10 text-foreground" : "border-border bg-background text-muted-foreground hover:border-foreground/20"}`}>
          <span className="text-sm leading-none">{e}</span><span className="font-medium tabular-nums">{who.length}</span>
        </button>
      ))}
      {onReact && <ReactButton onReact={onReact} />}
    </div>
  );
}

// Pictures sent with a message, shown as themselves: one at its own size, several in a grid. A click opens the
// canvas. Each is fetched once a chat (use-chat), a soft frame until it is.
function Pictures({ items, onOpenFile }: { items: Attachment[]; onOpenFile?: (path: string) => void }) {
  const one = items.length === 1;
  return (
    <div className={one ? "max-w-full" : `grid max-w-sm gap-1.5 ${items.length === 2 || items.length === 4 ? "grid-cols-2" : "grid-cols-3"}`}>
      {items.map((a, i) => (
        <button key={a.path || i} type="button" onClick={() => a.path && onOpenFile?.(a.path)} aria-label={a.name}
                className={`block overflow-hidden rounded-2xl border border-border bg-secondary cursor-pointer ${one ? "w-fit max-w-full" : "aspect-square"}`}>
          {a.url ? <img src={a.url} alt={a.name} className={one ? "block max-h-80 max-w-[min(20rem,100vw_-_5rem)]" : "size-full object-cover"} />
            : <span className={`block animate-pulse ${one ? "h-48 w-64 max-w-full" : "size-full"}`} />}
        </button>
      ))}
    </div>
  );
}

// A video sent with a message: a tile, played here when pressed, its file fetched only then.
function VideoTile({ att, resolve }: { att: Attachment; resolve?: (path: string) => Promise<string> }) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  if (src) return <video src={src} controls autoPlay playsInline className="block max-h-80 max-w-[min(22rem,100vw_-_5rem)] rounded-2xl border border-border bg-black" />;
  const play = async () => {
    if (!resolve || !att.path || loading) return;
    setLoading(true);
    try { setSrc(await resolve(att.path)); } catch { /* the canvas still opens it */ } finally { setLoading(false); }
  };
  return (
    <button type="button" onClick={() => void play()} aria-label={att.name}
            className="relative flex aspect-video w-72 max-w-full items-center justify-center overflow-hidden rounded-2xl border border-border bg-neutral-900 text-white cursor-pointer">
      <span className="flex size-12 items-center justify-center rounded-full bg-white/15 backdrop-blur-sm">
        {loading ? <span className="size-5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          : <svg className="ms-0.5 size-5" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" /></svg>}
      </span>
      <span dir="auto" className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 to-transparent px-3 pb-2 pt-6 text-start text-xs">{att.name}</span>
    </button>
  );
}

function UserBubble({ message, team, anchor, first = true, last = true, reactions, onReact, onReply, onRewrite, onOpenFile, resolveMedia }: BubbleProps) {
  const [editing, setEditing] = useState<string | null>(null);
  const [shown, setShown] = useState(false);   // a phone's tap on the message shows its tools
  const attachments = message.deleted ? [] : message.attachments || [];
  const kind = (a: Attachment) => (a.path && a.type.startsWith("image/") ? "picture" : a.path && a.type.startsWith("video/") ? "video" : "file");
  const pictures = attachments.filter((a) => kind(a) === "picture");
  const files = attachments.filter((a) => kind(a) === "file");
  const other = message.by && !message.by.you ? message.by : null;   // a teammate's, in a team chat
  const save = async () => {
    const text = editing?.trim();
    if (text && text !== message.content) await onRewrite?.(text).catch(() => {});
    setEditing(null);
  };
  const tools = team && !message.deleted && editing === null && (
    <Tools className={`absolute top-1/2 -translate-y-1/2 ${other ? "start-full ms-2" : "end-full me-2"}`} shown={shown} onReact={onReact} onReply={onReply}
           onEdit={!other && onRewrite ? () => setEditing(message.content) : undefined}
           onDelete={!other && onRewrite ? () => void onRewrite().catch(() => {}) : undefined} />
  );
  return (
    <div id={anchor} onClick={() => { if (team && window.matchMedia?.("(hover: none)").matches) setShown((v) => !v); }}
         className={`group flex w-full max-w-3xl gap-2.5 px-6 ${!team ? "pb-2" : last ? "pb-4" : "pb-1"} ${other ? "items-start justify-start" : "items-end justify-end"}`}>
      {other && <span className="w-7 shrink-0">{first && <Face c={{ by: other, at: "" }} size={28} />}</span>}
      <div className={`flex min-w-0 max-w-[80%] flex-col gap-1 ${other ? "items-start" : "items-end"}`}>
        {team && first && (other ? <Byline name={other.name || t("someone")} at={message.at} />
          : message.at && <span className="px-1 text-xs text-muted-foreground">{clock(message.at)}</span>)}
        {message.selection && <SelectionChip selection={message.selection} />}
        {message.reply && !message.deleted && (
          <Quoted name={quoteName(message.reply, team)} text={message.reply.text} onClick={() => findQuoted(message.reply!.id)} />
        )}
        <div className={`relative flex flex-col gap-2 ${other ? "items-start" : "items-end"}`}>
        {tools}
        {pictures.length > 0 && <Pictures items={pictures} onOpenFile={onOpenFile} />}
        {attachments.filter((a) => kind(a) === "video").map((a) => <VideoTile key={a.path} att={a} resolve={resolveMedia} />)}
        {files.length > 0 && (
          <div className={`flex flex-row gap-2 flex-wrap ${other ? "justify-start" : "justify-end"}`}>
            {files.map((att, i) => {   // a file kept in the workspace opens in the canvas, as the agent's do
              const tile = "border border-border bg-background hover:bg-secondary/50 flex items-center gap-3 rounded-2xl p-2 pr-3 transition-colors cursor-pointer";
              return att.path && onOpenFile
                ? <button key={att.name + i} type="button" onClick={() => onOpenFile(att.path!)} className={tile}><AttachmentBody attachment={att} /></button>
                : <a key={att.name + i} href={att.url} target="_blank" rel="noopener noreferrer" className={tile}><AttachmentBody attachment={att} /></a>;
            })}
          </div>
        )}
        {editing !== null ? (
          <div className="flex w-[min(28rem,70vw)] flex-col gap-2 rounded-2xl border border-border bg-background p-2">
            <textarea autoFocus value={editing} dir={dirOf(editing)} rows={Math.min(6, editing.split("\n").length)}
                      onChange={(e) => setEditing(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void save(); }
                        if (e.key === "Escape") setEditing(null);
                      }}
                      className="w-full resize-none bg-transparent px-2 py-1 text-sm outline-none" />
            <div className="flex justify-end gap-1">
              <button type="button" onClick={() => setEditing(null)} className="rounded-full px-3 py-1 text-xs hover:bg-secondary cursor-pointer">{t("cancel")}</button>
              <button type="button" onClick={() => void save()} className="rounded-full bg-foreground px-3 py-1 text-xs text-background hover:opacity-80 cursor-pointer">{t("save")}</button>
            </div>
          </div>
        ) : (message.content || message.deleted) && (
          <div dir={dirOf(message.content)} className="rounded-3xl bg-secondary text-secondary-foreground px-4 py-2.5 whitespace-pre-wrap break-words">
            {message.deleted ? <span className="italic text-muted-foreground">{t("messageDeleted")}</span>
              : team ? <Mentioned text={message.content} names={team.names} /> : message.content}
          </div>
        )}
        </div>
        {message.edited && !message.deleted && <span className="px-1 text-[11px] text-muted-foreground">{t("edited")}</span>}
        <Reactions on={reactions} team={team} onReact={onReact} />
      </div>
    </div>
  );
}

// Who wrote a team chat's message, beside their face: the name, then the time.
function Byline({ name, at }: { name: string; at?: string | number }) {
  return (
    <div className="flex h-7 items-center gap-2">
      <span className="text-sm font-medium text-foreground">{name}</span>
      {at && <span className="text-xs text-muted-foreground">{clock(at)}</span>}
    </div>
  );
}

function Reply({ message, team, anchor, reactions, onReact, onReply, isStreaming, onRetry, onRegenerate, onOpenFile, resolveMedia }: BubbleProps) {
  const [copied, setCopied] = useState(false);
  const parts = (message.parts || [])
    .filter((p) => p.type !== "chat_id")
    // Collapse consecutive canvas cards for the same file (retries) into one.
    .filter((p, i, all) => {
      if (p.type !== "step" || p.tool_name !== "Canvas") return true;
      const next = all[i + 1];
      return !(next?.type === "step" && next.tool_name === "Canvas" && next.step === p.step);
    });
  // `sources` parts don't render where they land — one chip row per search
  // repeated the same domains through the turn. They're merged and deduped
  // into a single row at the END of the message instead, which is also the
  // only thing that guarantees provenance is visible: citing inline is the
  // model's choice, and a turn where it searches but doesn't cite would
  // otherwise show no sources at all.
  //
  // `suggest` and `ask` drive the composer, not the transcript. Their step
  // line restated a chip or a card the user is already looking at, and padded
  // the "N steps" count with work that isn't work.
  // A search's results ride into its own step row, threaded by the id of the call that ran them, and
  // expand under the query there. The deduped chip row at the end of the turn stays: provenance can't
  // depend on the reader opening a step.
  const byCall = new Map<string, Source[]>();
  for (const p of parts) if (p.type === "sources" && p.id && p.sources?.length) byCall.set(p.id, p.sources);
  // A picture a tool made shows as itself, so its step goes (one that failed keeps its row), and its file keeps
  // the shape it was made in.
  const made = new Set(parts.flatMap((p) => (p.type === "step" && p.id?.endsWith(":file") ? [p.id.slice(0, -5)] : [])));
  const shapes = new Map(parts.flatMap((p): [string, string][] => (p.type === "step" && p.picture && p.id ? [[`${p.id}:file`, p.picture]] : [])));
  // Text that is only whitespace (a model's newline between tool calls) renders nothing, and the stream's end drops
  // it anyway: kept until then, it split a run of steps live that a reload shows as one.
  const rendered = parts
    .filter((p) => p.type && !(p.type === "text" && !p.text?.trim()))
    .filter((p) => p.type !== "sources" && p.type !== "usage" && !(p.type === "step" && (p.tool_name === "Suggest" || p.tool_name === "Ask")))
    .filter((p) => !(p.type === "step" && p.picture && p.id && made.has(p.id)))
    .map((p) => (p.type === "step" && p.id && shapes.has(p.id) ? { ...p, picture: shapes.get(p.id) } : p))
    .map((p) => (p.type === "step" && p.id && byCall.has(p.id) ? { ...p, sources: byCall.get(p.id) } : p));
  const isEmpty = rendered.length === 0;
  const at = parts.find((p) => typeof p.at === "number")?.at;   // when the reply began, for one with no time of its own
  // A limit is the line over the message box; in a reply it is the note, and only where it is the whole of one:
  // the reply it refused.
  const refused = isEmpty && !isStreaming ? parts.find((p) => p.type === "usage" && usedUp(p)) : undefined;

  // Every result this turn's searches returned, keyed for link lookup. `parts`
  // is rebuilt on every streamed token, so the memo keys on the URLs instead —
  // a churning map identity would re-render every markdown block per token.
  const sourceKey = parts
    .filter((p) => p.type === "sources")
    .map((p) => (p.sources || []).map((s) => s.url).join(","))
    .join("|");
  const sourceIndex = useMemo(() => {
    if (!sourceKey) return undefined;
    const map = new Map<string, Source>();
    for (const p of parts) {
      if (p.type !== "sources") continue;
      for (const s of p.sources || []) if (s.url) map.set(urlKey(s.url), s);
    }
    return map.size ? map : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  // Deduped by `urlKey`, so the same article returned by two searches is one
  // chip. Held back until the turn ends — appended live it would shunt itself
  // down the page on every streamed token.
  const allSources = useMemo(() => (sourceIndex ? [...sourceIndex.values()] : []), [sourceIndex]);

  const copyAll = () => {
    const text = parts
      .filter((p) => p.type === "text")
      .map((p) => p.text)
      .join("");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div id={anchor} className={`group flex w-full max-w-3xl items-start px-6 ${team ? "gap-2.5 pb-4" : "gap-4 pb-2"}`}>
      {team && <AgentMark logo={team.logo} name={team.agent} size={28} />}
      <div className="relative flex min-w-0 flex-1 flex-col gap-1">
        {team && (
          <div className="flex items-center gap-2">
            <Byline name={team.agent} at={message.at || at} />
            {onReact && !isStreaming && <Tools onReact={onReact} onReply={onReply} />}
          </div>
        )}
        {isEmpty && isStreaming && <Loader />}
        {refused && <UsageNote usage={refused} />}

        {groupParts(rendered, isStreaming).map((group, gi, all) => {
          if (group.kind === "step" && group.items.some((p) => p.type === "step"))
            return <StepGroup key={gi} items={group.items} live={isStreaming && gi === all.length - 1}
                              end={rendered[group.startIndex + group.items.length]?.at} />;
          if (group.kind === "media")
            return <Gallery key={gi} items={group.items} resolve={resolveMedia} onOpenFile={onOpenFile} />;
          if (group.kind === "file")
            return <FilePart key={gi} path={group.items[0].step || ""} onOpen={onOpenFile} />;
          if (group.kind === "agents") return <AgentsCard key={gi} items={group.items} />;
          return group.items.map((part, i) =>
            renderPart(part, group.startIndex + i,
              isStreaming && group.startIndex + i === rendered.length - 1, onRetry, onOpenFile, sourceIndex));
        })}

        {!isStreaming && allSources.length > 0 && <SourcesPart sources={allSources} />}
        <Reactions on={reactions} team={team} onReact={onReact} />

        {/* Actions */}
        {!isEmpty && !isStreaming && (
          <div
            className={cn(
              "flex gap-0 -ms-2 opacity-100 sm:opacity-0 transition-opacity sm:group-hover:opacity-100 sm:has-[[data-open]]:opacity-100",
            )}
          >
            <button
              onClick={copyAll}
              className="hover:bg-secondary text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full transition cursor-pointer"
              aria-label="Copy"
              type="button"
            >
              <Icon name={copied ? "check" : "copy"} className="w-3.5 h-3.5" />
            </button>
            {onRegenerate && (
              <button
                onClick={onRegenerate}
                className="hover:bg-secondary text-muted-foreground hover:text-foreground flex size-7 items-center justify-center rounded-full transition cursor-pointer"
                aria-label={t("regenerate")}
                title={t("regenerate")}
                type="button"
              >
                <Icon name="refresh" className="w-3.5 h-3.5" />
              </button>
            )}
            {team && onReact && <span className="[@media(hover:hover)]:hidden"><ReactButton onReact={onReact} /></span>}
            {team && onReply && <span className="[@media(hover:hover)]:hidden"><ReplyButton onReply={onReply} /></span>}
          </div>
        )}
      </div>
    </div>
  );
}

// Three Cycls stars while the reply has not begun: two still, the hollow third turning.
function Loader() {
  return (
    <div className="flex items-center gap-0.5 py-3 text-foreground/70">
      <Star size={16} />
      <Star size={16} />
      <GlowStar spin />
    </div>
  );
}
