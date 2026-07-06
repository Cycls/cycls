import { useEffect, useRef, useState } from "react";
import { t } from "../lib/i18n";
import { Popover } from "./popover";
import { Icon } from "./icon";
import type { WorkspaceInfo, MemberInfo } from "../hooks/use-workspaces";

export interface WorkspacesMenu {
  active: WorkspaceInfo | null;   // null = personal
  items: WorkspaceInfo[];
  canCreate: boolean;
  orgMembers: { id: string; name: string }[];
  onSwitch: (id: string | null) => void;
  onCreate: (name: string) => Promise<WorkspaceInfo>;
  onDelete: (id: string) => Promise<void>;
  fetchMembers: (id: string) => Promise<MemberInfo[]>;
  onSetMember: (id: string, userId: string, role: string) => Promise<void>;
  onRemoveMember: (id: string, userId: string) => Promise<void>;
}

export function WorkspaceSwitcher({ workspaces }: { workspaces: WorkspacesMenu }) {
  const [open, setOpen] = useState(false);
  const [manageWs, setManageWs] = useState<WorkspaceInfo | null>(null);
  const [wsMembers, setWsMembers] = useState<MemberInfo[] | null>(null);
  const [newWsName, setNewWsName] = useState<string | null>(null);

  const close = () => { setOpen(false); setManageWs(null); setNewWsName(null); };

  // id-keyed deps: the menu prop is rebuilt every parent render, object deps would refetch in a loop
  const fetchRef = useRef(workspaces.fetchMembers);
  fetchRef.current = workspaces.fetchMembers;
  useEffect(() => {
    if (!manageWs || manageWs.builtin) { setWsMembers(null); return; }
    let alive = true;
    setWsMembers(null);
    fetchRef.current(manageWs.id).then((m) => alive && setWsMembers(m)).catch(() => alive && setWsMembers([]));
    return () => { alive = false; };
  }, [manageWs?.id, manageWs?.builtin]);   // eslint-disable-line react-hooks/exhaustive-deps

  const refreshMembers = () => manageWs && fetchRef.current(manageWs.id).then(setWsMembers);
  const memberName = (id: string) => workspaces.orgMembers.find((m) => m.id === id)?.name || id;
  const row = "flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer";
  const inactive = "text-muted-foreground hover:text-foreground hover:bg-secondary/80";

  return (
    <div className="relative">
      <button
        onClick={() => (open ? close() : setOpen(true))}
        className="flex items-center gap-1 px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg transition-colors cursor-pointer"
        aria-label={t("workspaceSection")}
      >
        <span className="max-w-[8rem] truncate">{workspaces.active?.name || t("personal")}</span>
        <Icon name="chevron-down" className="w-3 h-3" />
      </button>
      <Popover open={open} onClose={close} className="right-2 top-12 mt-2 w-64 rounded-lg border border-border bg-background shadow-lg">
        {manageWs ? (
          <div>
            <button onClick={() => setManageWs(null)} className={`${row} py-2.5 ${inactive}`}>
              <Icon name="chevron-left" className="w-3.5 h-3.5 rtl:rotate-180" />
              <span className="truncate">{manageWs.name}</span>
            </button>
            <div className="border-t border-border" />
            <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("members")}</p>
            {manageWs.builtin ? (
              <p className="px-3 py-1.5 text-sm text-muted-foreground">{t("everyoneInOrg")}</p>
            ) : wsMembers === null ? (
              <p className="px-3 py-1.5 text-sm text-muted-foreground">…</p>
            ) : (
              <div className="py-1">
                {wsMembers.map((m) => (
                  <div key={m.user_id} className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground">
                    <span className="truncate flex-1">{memberName(m.user_id)}</span>
                    {m.role === "owner" ? (
                      <span className="text-[10px] text-muted-foreground/60">{m.role}</span>
                    ) : (
                      <>
                        <button
                          onClick={() => workspaces.onSetMember(manageWs.id, m.user_id, m.role === "editor" ? "admin" : "editor").then(refreshMembers)}
                          className="text-[10px] text-muted-foreground/60 hover:text-foreground cursor-pointer"
                          title="Toggle role"
                        >
                          {m.role}
                        </button>
                        <button
                          onClick={() => workspaces.onRemoveMember(manageWs.id, m.user_id).then(refreshMembers)}
                          className="text-muted-foreground/60 hover:text-foreground cursor-pointer"
                          aria-label="Remove member"
                        >
                          <Icon name="x" className="w-3 h-3" />
                        </button>
                      </>
                    )}
                  </div>
                ))}
                {(() => {
                  const outside = workspaces.orgMembers.filter((om) => !wsMembers.some((m) => m.user_id === om.id));
                  if (!outside.length) return null;
                  return (
                    <>
                      <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("addMembers")}</p>
                      {outside.map((om) => (
                        <button key={om.id} onClick={() => workspaces.onSetMember(manageWs.id, om.id, "editor").then(refreshMembers)} className={`${row} ${inactive}`}>
                          + {om.name}
                        </button>
                      ))}
                    </>
                  );
                })()}
              </div>
            )}
            {(manageWs.role === "owner" || (manageWs.builtin && manageWs.role === "admin")) && (
              <>
                <div className="border-t border-border" />
                <button
                  onClick={() => {
                    if (!window.confirm(t("deleteWorkspaceConfirm"))) return;
                    const wasActive = workspaces.active?.id === manageWs.id;
                    workspaces.onDelete(manageWs.id).then(() => {
                      setManageWs(null);
                      if (wasActive) workspaces.onSwitch(null);
                    });
                  }}
                  className={`${row} py-2.5 text-red-500/80 hover:text-red-500 hover:bg-secondary/80`}
                >
                  {t("deleteWorkspace")}
                </button>
              </>
            )}
          </div>
        ) : (
          <div>
            <div className="py-1">
              <button
                onClick={() => { workspaces.onSwitch(null); close(); }}
                className={`${row} ${!workspaces.active ? "text-foreground bg-secondary/60" : inactive}`}
              >
                {t("personal")}
              </button>
              {workspaces.items.filter((w) => w.type === "team").map((w) => (
                <div
                  key={w.id}
                  className={`flex w-full items-center gap-1 pl-3 pr-2 text-sm transition-colors ${workspaces.active?.id === w.id ? "text-foreground bg-secondary/60" : inactive}`}
                >
                  <button onClick={() => { workspaces.onSwitch(w.id); close(); }} className="flex-1 truncate py-1.5 text-start cursor-pointer">
                    {w.name}
                  </button>
                  {(w.role === "owner" || w.role === "admin") && (
                    <button
                      onClick={() => setManageWs(w)}
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
                      if (e.key === "Escape") setNewWsName(null);
                      if (e.key === "Enter" && newWsName.trim()) {
                        workspaces.onCreate(newWsName.trim()).then((r) => { workspaces.onSwitch(r.id); close(); });
                      }
                    }}
                    placeholder={t("workspaceSection")}
                    className="w-full px-3 py-2.5 text-sm bg-transparent text-foreground outline-none placeholder:text-muted-foreground/50"
                  />
                )}
              </>
            )}
          </div>
        )}
      </Popover>
    </div>
  );
}
