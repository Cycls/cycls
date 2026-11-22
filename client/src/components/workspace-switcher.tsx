import { useState } from "react";
import { t } from "../lib/i18n";
import { Icon } from "./icon";
import { EmojiPicker } from "./emoji-picker";
import { Face } from "./file-details";
import type { Everywhere, WorkspaceInfo, MemberInfo } from "../hooks/use-workspaces";

export interface WorkspacesMenu {
  active: WorkspaceInfo | null;   // null = personal
  items: WorkspaceInfo[];
  canCreate: boolean;
  isOrgAdmin: boolean;
  orgMembers: OrgMember[];
  orgMembersComplete?: boolean;   // every page is in: a member missing from it has left the org
  onManage?: (id: string) => void;   // open Settings → Workspaces on this one
  onSwitch: (id: string | null) => void;
  onCreate: (name: string) => Promise<WorkspaceInfo>;
  onUpdate: (id: string, patch: { name?: string; icon?: string }) => Promise<WorkspaceInfo>;
  onDelete: (id: string) => Promise<void>;
  fetchMembers: (id: string) => Promise<MemberInfo[]>;
  onSetMember: (id: string, userId: string, role: string) => Promise<void>;
  onRemoveMember: (id: string, userId: string) => Promise<void>;
  search?: (query: string) => Promise<Everywhere>;
}

export type OrgMember = { id: string; name: string; email?: string; image?: string };

// A workspace member's name: the org's record of them, "Former member" once they've left it, "…" until the list is in.
export const nameIn = (ws: WorkspacesMenu, id: string) =>
  ws.orgMembers.find((m) => m.id === id)?.name || (ws.orgMembersComplete ? t("formerMember") : "…");

// The people a picker offers, narrowed by what was typed: a name or an email.
export const findIn = (people: OrgMember[], q: string) =>
  people.filter((m) => !q || `${m.name} ${m.email ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()));
export const SEARCH_FROM = 8;   // shorter lists don't need a search box

// Notion-style workspace icon: the stored emoji, else the name's initial.
export function WsIcon({ ws, className = "" }: { ws: { name: string; icon?: string } | null; className?: string }) {
  if (ws?.icon) return <span className={`w-4 text-center shrink-0 ${className}`}>{ws.icon}</span>;
  return (
    <span className={`size-4 rounded bg-secondary text-[9px] font-medium text-muted-foreground flex items-center justify-center shrink-0 select-none ${className}`}>
      {(ws?.name || t("personal")).charAt(0).toUpperCase()}
    </span>
  );
}

// The workspace list: it switches, and its members button opens Settings on that workspace, where it is managed.
// `onClose` closes the menu after a switch.
function WorkspacePanel({ workspaces, onClose }: { workspaces: WorkspacesMenu; onClose: () => void }) {
  const [newWsName, setNewWsName] = useState<string | null>(null);
  const [pickerFor, setPickerFor] = useState<string | null>(null);
  const row = "flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer";
  const inactive = "text-muted-foreground hover:text-foreground hover:bg-secondary/80";

  return (
    <div>
      <div className="py-1">
        <button
          onClick={() => { workspaces.onSwitch(null); onClose(); }}
          className={`${row} ${!workspaces.active ? "text-foreground bg-secondary/60" : inactive}`}
        >
          <WsIcon ws={null} />
          {t("personal")}
        </button>
        {workspaces.items.filter((w) => w.type === "team").map((w) => (
          <div
            key={w.id}
            className={`relative flex w-full items-center gap-1 pl-2 pr-2 text-sm transition-colors ${workspaces.active?.id === w.id ? "text-foreground bg-secondary/60" : inactive}`}
          >
            {(w.role === "owner" || w.role === "admin" || workspaces.isOrgAdmin) ? (
              <button
                onClick={(e) => { e.stopPropagation(); setPickerFor(pickerFor === w.id ? null : w.id); }}
                className="cursor-pointer rounded p-1 hover:bg-secondary"
                aria-label={t("icon")}
              >
                <WsIcon ws={w} />
              </button>
            ) : (
              <span className="p-1"><WsIcon ws={w} /></span>
            )}
            {pickerFor === w.id && (
              <EmojiPicker
                align="right"
                onPick={(e) => { setPickerFor(null); workspaces.onUpdate(w.id, { icon: e }); }}
                onClear={w.icon ? () => { setPickerFor(null); workspaces.onUpdate(w.id, { icon: "" }); } : undefined}
                onClose={() => setPickerFor(null)}
              />
            )}
            <button onClick={() => { workspaces.onSwitch(w.id); onClose(); }} className="flex flex-1 items-center gap-2 truncate py-1.5 text-start cursor-pointer">
              <span className="truncate">{w.name}</span>
            </button>
            {(w.role === "owner" || w.role === "admin") && workspaces.onManage && (
              <button
                onClick={() => { workspaces.onManage?.(w.id); onClose(); }}
                className="text-muted-foreground/60 hover:text-foreground cursor-pointer p-1"
                aria-label={t("members")}
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
                </svg>
              </button>
            )}
          </div>
        ))}
      </div>
      {workspaces.canCreate && (
        <>
          <div className="border-t border-border" />
          {newWsName === null ? (
            <button onClick={() => setNewWsName("")} className={`${row} py-2.5 ${inactive}`}>
              {t("newWorkspace")}
            </button>
          ) : (
            <input
              autoFocus
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") { e.preventDefault(); setNewWsName(null); }
                if (e.key === "Enter" && newWsName.trim()) {
                  workspaces.onCreate(newWsName.trim()).then((r) => { workspaces.onSwitch(r.id); onClose(); });
                }
              }}
              placeholder={t("workspaceSection")}
              className="w-full px-3 py-2.5 text-sm bg-transparent text-foreground outline-none placeholder:text-muted-foreground/50"
            />
          )}
        </>
      )}
    </div>
  );
}


// The switcher as its own control beside the avatar: the active workspace is
// visible without opening anything, and switching is one click instead of
// three (avatar → Workspaces → pick).
// Beside the agent's name, Super / Research, its list opening under it; on a phone the workspace's icon alone.
export function WorkspaceMenu({ workspaces }: { workspaces: WorkspacesMenu }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 max-w-44 items-center gap-1.5 px-1 text-[15px] text-foreground transition-opacity hover:opacity-70 cursor-pointer"
        aria-label={t("workspaces")}
      >
        <WsIcon ws={workspaces.active} />
        <span className="truncate max-sm:hidden">{workspaces.active?.name || t("personal")}</span>
        <Icon name="chevron-down" className="size-3 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <>
          {/* Anchored to this button, not the viewport — `Popover` portals to
              document.body, which put the panel at the far edge of the page. */}
          <div className="fixed inset-0 z-[70]" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-[80] mt-1 w-56 rounded-lg border border-border bg-background shadow-lg">
            <WorkspacePanel workspaces={workspaces} onClose={() => setOpen(false)} />
          </div>
        </>
      )}
    </div>
  );
}

// A team workspace's people: beside its name on a computer (`TeamPeople`), never on a phone.
export type People = {
  members: { id: string; name: string; image?: string; you?: boolean }[];
  ws: WorkspaceInfo; onManage?: () => void;
};

export function Faces({ members, size = 22 }: { members: People["members"]; size?: number }) {
  const others = members.filter((m) => !m.you);
  return (
    <span className="flex shrink-0">
      {(others.length ? others : members).slice(0, 3).map((m, i) => (
        <span key={m.id} className="rounded-full ring-2 ring-background" style={{ marginInlineStart: i ? -6 : 0 }}><Face c={{ by: m, at: "" }} size={size} /></span>
      ))}
    </span>
  );
}

// The workspace's people, you first; Manage people for its admins.
export function PeopleList({ members, ws, onManage, onClose }: People & { onClose: () => void }) {
  return (
    <>
      <div className="flex items-baseline justify-between gap-2 px-3 pb-1.5 pt-3">
        <span className="truncate text-sm font-medium text-foreground">{ws.name}</span>
        <span className="text-xs text-muted-foreground">{members.length}</span>
      </div>
      {ws.builtin && <div className="-mt-1 px-3 pb-1.5 text-xs text-muted-foreground">{t("everyoneInOrg")}</div>}
      <div className="max-h-80 overflow-y-auto py-1">
        {[...members.filter((m) => m.you), ...members.filter((m) => !m.you)].map((m) => (
          <div key={m.id} className="flex items-center gap-2.5 px-3 py-1.5">
            <Face c={{ by: m, at: "" }} size={26} />
            <span className="flex-1 truncate text-sm text-foreground">{m.name}</span>
            {m.you && <span className="text-xs text-muted-foreground">{t("you")}</span>}
          </div>
        ))}
      </div>
      {onManage && (
        <button onClick={() => { onClose(); onManage(); }}
                className="w-full border-t border-border px-3 py-2 text-start text-xs font-medium text-foreground hover:bg-secondary/60 cursor-pointer">
          {t("managePeople")}
        </button>
      )}
    </>
  );
}

export function TeamPeople(people: People) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative max-sm:hidden">
      <button onClick={() => setOpen((o) => !o)} aria-label={t("members")}
              className="flex h-9 items-center gap-1.5 text-[13px] transition-opacity hover:opacity-70 cursor-pointer">
        <Faces members={people.members} size={25} />
        <span className="text-foreground">{people.members.length}</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-[70]" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-[80] mt-1 w-72 overflow-hidden rounded-xl border border-border bg-background shadow-lg">
            <PeopleList {...people} onClose={() => setOpen(false)} />
          </div>
        </>
      )}
    </div>
  );
}
