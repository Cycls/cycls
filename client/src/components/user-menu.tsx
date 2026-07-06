import { useEffect, useState } from "react";
import { t } from "../lib/i18n";
import { toggleDark } from "../lib/utils";
import { Popover } from "./popover";
import { Icon } from "./icon";
import type { WorkspaceInfo, MemberInfo } from "../hooks/use-workspaces";

export interface UserInfo {
  name: string;
  email: string;
  imageUrl?: string;
}

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

export interface PlanInfo {
  name: string;
  status: string;
  periodEnd: Date | null;
  canceledAt: Date | null;
  amount?: { amountFormatted: string; currencySymbol: string };
  planPeriod: string;
}

export function UserMenu({ user, onSignOut, onManageAccount, onCreateOrg, onManageOrg, onSwitchOrg, activeOrg, orgs, plan, onOpenPlans, workspaces }: {
  user: UserInfo;
  onSignOut?: () => void;
  onManageAccount?: () => void;
  onCreateOrg?: () => void;
  onManageOrg?: () => void;
  onSwitchOrg?: (orgId: string | null) => void;
  activeOrg?: { id: string; name: string; imageUrl?: string };
  orgs?: { id: string; name: string; imageUrl: string }[];
  plan?: PlanInfo;
  onOpenPlans?: () => void;
  workspaces?: WorkspacesMenu;
}) {
  const [open, setOpen] = useState(false);
  const [showOrgs, setShowOrgs] = useState(false);
  const [showWs, setShowWs] = useState(false);
  const [manageWs, setManageWs] = useState<WorkspaceInfo | null>(null);
  const [wsMembers, setWsMembers] = useState<MemberInfo[] | null>(null);
  const [newWsName, setNewWsName] = useState<string | null>(null);

  const closeAll = () => { setShowOrgs(false); setShowWs(false); setManageWs(null); setNewWsName(null); };

  useEffect(() => {
    if (!manageWs || manageWs.builtin) return;
    setWsMembers(null);
    workspaces?.fetchMembers(manageWs.id).then(setWsMembers).catch(() => setWsMembers([]));
  }, [manageWs, workspaces]);

  const refreshMembers = () => manageWs && workspaces?.fetchMembers(manageWs.id).then(setWsMembers);
  const memberName = (id: string) => workspaces?.orgMembers.find((m) => m.id === id)?.name || id;

  return (
    <div className="relative">
      <button
        onClick={() => { setOpen(!open); closeAll(); }}
        className="flex items-center justify-center rounded-lg hover:opacity-80 transition-opacity cursor-pointer px-1 h-8"
        aria-label="Profile"
      >
        <div className="flex items-center -space-x-2">
          {activeOrg?.imageUrl && (
            <div
              className="size-6 rounded-full bg-secondary shrink-0 ring-2 ring-background"
              style={{ backgroundImage: `url(${activeOrg.imageUrl})`, backgroundSize: "cover" }}
            />
          )}
          <div
            className="size-6 rounded-full bg-secondary text-foreground flex items-center justify-center text-xs font-medium select-none ring-2 ring-background"
            style={user.imageUrl ? { backgroundImage: `url(${user.imageUrl})`, backgroundSize: "cover" } : undefined}
          >
            {!user.imageUrl && (user.name?.charAt(0) || user.email?.charAt(0) || "?")}
          </div>
        </div>
      </button>
      <Popover open={open} onClose={() => { setOpen(false); closeAll(); }} className="right-2 top-12 mt-2 w-56 rounded-lg border border-border bg-background shadow-lg">
        <div>
            {manageWs && workspaces ? (
              <>
                <button
                  onClick={() => setManageWs(null)}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <Icon name="chevron-left" className="w-3.5 h-3.5 rtl:rotate-180" />
                  {manageWs.name}
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
                      return outside.length ? (
                        <>
                          <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("addMembers")}</p>
                          {outside.map((om) => (
                            <button
                              key={om.id}
                              onClick={() => workspaces.onSetMember(manageWs.id, om.id, "editor").then(refreshMembers)}
                              className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                            >
                              + {om.name}
                            </button>
                          ))}
                        </>
                      ) : null;
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
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-red-500/80 hover:text-red-500 hover:bg-secondary/80 transition-colors cursor-pointer"
                    >
                      {t("deleteWorkspace")}
                    </button>
                  </>
                )}
              </>
            ) : showWs && workspaces ? (
              <>
                <button
                  onClick={() => { setShowWs(false); setNewWsName(null); }}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <Icon name="chevron-left" className="w-3.5 h-3.5 rtl:rotate-180" />
                  {t("back")}
                </button>
                <div className="border-t border-border" />
                <div className="py-1">
                  <button
                    onClick={() => { workspaces.onSwitch(null); closeAll(); }}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer ${!workspaces.active ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                  >
                    {t("personal")}
                  </button>
                  {workspaces.items.filter((w) => w.type === "team").map((w) => (
                    <div
                      key={w.id}
                      className={`flex w-full items-center gap-1 pl-3 pr-2 text-sm transition-colors ${workspaces.active?.id === w.id ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                    >
                      <button onClick={() => { workspaces.onSwitch(w.id); closeAll(); }} className="flex-1 truncate py-1.5 text-start cursor-pointer">
                        {w.name}
                      </button>
                      {(w.role === "owner" || w.role === "admin") && (
                        <button
                          onClick={() => setManageWs(w)}
                          className="text-muted-foreground/60 hover:text-foreground cursor-pointer p-1"
                          aria-label={t("members")}
                        >
                          {/* one-off "members" icon — stays inline per icon.tsx convention */}
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
                      <button
                        onClick={() => setNewWsName("")}
                        className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                      >
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
                            workspaces.onCreate(newWsName.trim()).then((row) => { workspaces.onSwitch(row.id); closeAll(); setOpen(false); });
                          }
                        }}
                        placeholder={t("workspaceSection")}
                        className="w-full px-3 py-2.5 text-sm bg-transparent text-foreground outline-none placeholder:text-muted-foreground/50"
                      />
                    )}
                  </>
                )}
              </>
            ) : showOrgs ? (
              <>
                <button
                  onClick={() => setShowOrgs(false)}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <Icon name="chevron-left" className="w-3.5 h-3.5 rtl:rotate-180" />
                  {t("back")}
                </button>
                <div className="border-t border-border" />
                <div className="py-1">
                  <button
                    onClick={() => { onSwitchOrg?.(null); setShowOrgs(false); }}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer ${!activeOrg ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                  >
                    {t("personal")}
                  </button>
                  {(orgs || []).map((org) => (
                    <button
                      key={org.id}
                      onClick={() => { onSwitchOrg?.(org.id); setShowOrgs(false); }}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors cursor-pointer ${activeOrg?.id === org.id ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"}`}
                    >
                      {org.name}
                    </button>
                  ))}
                </div>
                {onCreateOrg && (
                  <>
                    <div className="border-t border-border" />
                    <button
                      onClick={() => { setOpen(false); setShowOrgs(false); onCreateOrg(); }}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    >
                      {t("createOrg")}
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <div className="flex items-center gap-2.5 px-3 py-2.5">
                  <div
                    className="size-8 rounded-full bg-secondary text-foreground flex items-center justify-center text-sm font-medium select-none shrink-0"
                    style={user.imageUrl ? { backgroundImage: `url(${user.imageUrl})`, backgroundSize: "cover" } : undefined}
                  >
                    {!user.imageUrl && (user.name?.charAt(0) || user.email?.charAt(0) || "?")}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{user.name}</p>
                    <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                  </div>
                </div>
                <div className="border-t border-border" />
                <button
                  onClick={() => toggleDark("user_menu")}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <Icon name="moon" />
                  {document.body.classList.contains("dark") ? t("lightMode") : t("darkMode")}
                </button>
                <div className="border-t border-border" />
                <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("account")}</p>
                {plan && onOpenPlans && (
                  <button
                    onClick={() => { setOpen(false); onOpenPlans(); }}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    {t("plans")}
                    <span className="text-[10px] text-muted-foreground/60">{plan.name}</span>
                  </button>
                )}
                <button
                  onClick={() => { setOpen(false); activeOrg && onManageOrg ? onManageOrg() : onManageAccount?.(); }}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  {activeOrg ? t("manageOrg") : t("manageAccount")}
                </button>
                {onSwitchOrg && (
                  <>
                  <div className="border-t border-border" />
                  <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("organization")}</p>
                  <button
                    onClick={() => setShowOrgs(true)}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    <span className="flex items-center gap-2 truncate">
                      {activeOrg?.imageUrl && (
                        <div className="size-4 rounded-full shrink-0" style={{ backgroundImage: `url(${activeOrg.imageUrl})`, backgroundSize: "cover" }} />
                      )}
                      {activeOrg ? activeOrg.name : t("personal")}
                    </span>
                    <Icon name="chevron-right" className="w-3.5 h-3.5 rtl:rotate-180" />
                  </button>
                  </>
                )}
                {workspaces && (
                  <>
                  <div className="border-t border-border" />
                  <p className="px-3 pt-2 pb-1 text-[8px] font-medium uppercase tracking-wider text-muted-foreground/40">{t("workspaceSection")}</p>
                  <button
                    onClick={() => setShowWs(true)}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                  >
                    <span className="truncate">{workspaces.active?.name || t("personal")}</span>
                    <Icon name="chevron-right" className="w-3.5 h-3.5 rtl:rotate-180" />
                  </button>
                  </>
                )}
                {onSignOut && (
                  <>
                    <div className="border-t border-border" />
                    <button
                      onClick={() => { setOpen(false); onSignOut(); }}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                    >
                      {t("signOut")}
                    </button>
                  </>
                )}
              </>
            )}
        </div>
      </Popover>
    </div>
  );
}
