import { useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../lib/i18n";
import { toggleDark } from "../lib/utils";

export interface UserInfo {
  name: string;
  email: string;
  imageUrl?: string;
}

export interface PlanInfo {
  name: string;
  status: string;
  periodEnd: Date | null;
  canceledAt: Date | null;
  amount?: { amountFormatted: string; currencySymbol: string };
  planPeriod: string;
}

export function UserMenu({ user, onSignOut, onManageAccount, onCreateOrg, onManageOrg, onSwitchOrg, activeOrg, orgs, plan, onOpenPlans }: {
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
}) {
  const [open, setOpen] = useState(false);
  const [showOrgs, setShowOrgs] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => { setOpen(!open); setShowOrgs(false); }}
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
      {open && createPortal(
        <>
          <div className="fixed inset-0 z-40" onClick={() => { setOpen(false); setShowOrgs(false); }} />
          <div className="fixed right-2 top-12 z-50 mt-2 w-56 rounded-lg border border-border bg-background shadow-lg">
            {showOrgs ? (
              <>
                <button
                  onClick={() => setShowOrgs(false)}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
                >
                  <svg className="w-3.5 h-3.5 rtl:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
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
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                  </svg>
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
                    <svg className="w-3.5 h-3.5 rtl:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
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
        </>,
        document.body
      )}
    </div>
  );
}
