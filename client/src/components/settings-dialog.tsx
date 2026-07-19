import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useClerk, useOrganization, useUser, useReverification } from "@clerk/clerk-react";
import { PaymentElement, PaymentElementProvider, usePaymentElement, SubscriptionDetailsButton } from "@clerk/clerk-react/experimental";
import { Icon } from "./icon";
import { InlineInput, DropdownMenu } from "./files";
import { LoadingBar } from "./loading-bar";
import { PricingCards } from "./pricing-cards";
import type { AccountInfo } from "./chat";
import type { WorkspacesMenu } from "./workspace-switcher";
import type { MemberInfo } from "../hooks/use-workspaces";
import { t, useLang, setLang, getLang } from "../lib/i18n";
import { cn, getThemeMode, setThemeMode, type ThemeMode } from "../lib/utils";
import { useDarkMode } from "../hooks/use-dark-mode";
import { useToast } from "../lib/toast";
import { track } from "../lib/posthog";

type Tab = "general" | "account" | "organization" | "members" | "workspaces" | "billing" | "security" | "help";

const TAB_ICONS: Record<Tab, React.ReactNode> = {
  general: <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28zM15 12a3 3 0 11-6 0 3 3 0 016 0z" />,
  account: <path strokeLinecap="round" strokeLinejoin="round" d="M17.982 18.725A7.488 7.488 0 0012 15.75a7.488 7.488 0 00-5.982 2.975m11.963 0a9 9 0 10-11.963 0m11.963 0A8.966 8.966 0 0112 21a8.966 8.966 0 01-5.982-2.275M15 9.75a3 3 0 11-6 0 3 3 0 016 0z" />,
  organization: <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />,
  members: <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />,
  workspaces: <path strokeLinecap="round" strokeLinejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />,
  billing: <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z" />,
  security: <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />,
  help: <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />,
};

const supportMail = (subject: string) =>
  window.open(`mailto:support@cycls.com?subject=${encodeURIComponent(subject)}`, "_blank");

const clerkMsg = (e: unknown) =>
  (e as { errors?: { message?: string }[]; message?: string })?.errors?.[0]?.message || (e as Error)?.message || "Something went wrong";

const dateLocale = () => (getLang() === "ar" ? "ar" : "en");
const fmtDate = (d: string | Date) => new Date(d).toLocaleDateString(dateLocale(), { month: "short", day: "numeric", year: "numeric" });
const fmtDateTime = (d: string | Date) => new Date(d).toLocaleString(dateLocale(), { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function SettingsDialog({ account, onClose }: {
  account: AccountInfo;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("account");
  const lang = useLang();
  const isAr = lang === "ar";
  const { membership } = useOrganization();
  const inOrg = !!account.activeOrg;
  const isAdmin = !inOrg || membership?.role === "org:admin";

  const tabs: Tab[] = [
    "account", "general",
    ...(inOrg ? ["organization" as Tab, "members" as Tab] : []),
    ...(inOrg && account.workspaces ? ["workspaces" as Tab] : []),
    ...(isAdmin ? ["billing" as Tab] : []),
    "security", "help",
  ];

  // Switching context can drop the current tab (e.g. workspaces → personal).
  useEffect(() => {
    setTab((cur) => (tabs.includes(cur) ? cur : "account"));
  }, [account.activeOrg?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { track("settings_opened", {}); }, []);

  const tabBtn = (k: Tab, mobile: boolean) => (
    <button
      key={k}
      onClick={() => setTab(k)}
      className={cn(
        "flex shrink-0 cursor-pointer items-center gap-2.5 text-sm transition-colors",
        mobile ? "rounded-full px-3.5 py-1.5" : "w-full rounded-lg px-3 py-2",
        tab === k ? "bg-secondary text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-secondary/50",
      )}
    >
      <svg className="size-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.6} viewBox="0 0 24 24">{TAB_ICONS[k]}</svg>
      {t(k)}
    </button>
  );

  return createPortal(
    <div dir={isAr ? "rtl" : "ltr"}>
      <div className="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      {/* bg-card: off-white in light, dark gray (not black) in dark — follows the body class. */}
      <div className="fixed inset-0 z-[80] flex flex-col overflow-hidden bg-card sm:inset-auto sm:left-1/2 sm:top-1/2 sm:h-[min(680px,88vh)] sm:w-[min(920px,94vw)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl sm:border sm:border-border sm:shadow-xl">
        {/* Mobile header, context selector + pill tabs */}
        <div className="sm:hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="text-lg font-semibold text-foreground">{t("settings")}</h2>
            <button onClick={onClose} className="cursor-pointer text-muted-foreground hover:text-foreground" aria-label="Close">
              <Icon name="x" className="size-5" />
            </button>
          </div>
          <div className="border-b border-border px-4 py-2.5">
            <ContextSelector account={account} />
          </div>
          <div className="flex gap-2 overflow-x-auto border-b border-border px-4 py-3">
            {tabs.map((k) => tabBtn(k, true))}
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          {/* Desktop rail */}
          <aside className="hidden w-60 shrink-0 flex-col gap-1 border-e border-border p-3 sm:flex">
            <button onClick={onClose} className="mb-2 flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary/80 hover:text-foreground" aria-label="Close">
              <Icon name="x" className="size-4" />
            </button>
            <div className="mb-3"><ContextSelector account={account} /></div>
            {tabs.map((k) => tabBtn(k, false))}
          </aside>

          <div className="min-w-0 flex-1 overflow-y-auto px-5 py-5 sm:px-8">
            <h2 className="mb-4 hidden text-lg font-semibold text-foreground sm:block">{t(tab)}</h2>
            {tab === "general" && <GeneralTab />}
            {tab === "account" && <AccountTab account={account} />}
            {tab === "organization" && <OrganizationTab account={account} isAdmin={isAdmin} />}
            {tab === "members" && <MembersTab isAdmin={isAdmin} />}
            {tab === "workspaces" && account.workspaces && <WorkspacesTab ws={account.workspaces} />}
            {tab === "billing" && <BillingTab account={account} />}
            {tab === "security" && <SecurityTab />}
            {tab === "help" && <HelpTab />}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// Personal ↔ organization context. The whole dialog (and the app behind it)
// follows this: org settings, members, workspaces and org billing appear in
// org context.
function ContextSelector({ account }: { account: AccountInfo }) {
  const [open, setOpen] = useState(false);
  const active = account.activeOrg;
  const avatar = (imageUrl?: string, name?: string) => (
    <span
      className="flex size-5 shrink-0 items-center justify-center rounded-md bg-secondary text-[10px] font-medium text-foreground"
      style={imageUrl ? { backgroundImage: `url(${imageUrl})`, backgroundSize: "cover" } : undefined}
    >
      {!imageUrl && (name?.charAt(0) || "P")}
    </span>
  );
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-border px-2.5 py-2 text-sm text-foreground transition-colors hover:bg-secondary/50"
      >
        {avatar(active?.imageUrl, active?.name)}
        <span className="min-w-0 flex-1 truncate text-start">{active?.name || t("personal")}</span>
        <Icon name="chevron-down" className="size-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-lg">
            <button onClick={() => { account.onSwitchOrg(null); setOpen(false); }}
              className={cn("flex w-full cursor-pointer items-center gap-2 px-2.5 py-2 text-sm", !active ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/50")}>
              {avatar(undefined, t("personal"))}
              <span className="truncate">{t("personal")}</span>
              {!active && <Icon name="check" className="ms-auto size-3.5" />}
            </button>
            {(account.orgs || []).map((org) => (
              <button key={org.id} onClick={() => { account.onSwitchOrg(org.id); setOpen(false); }}
                className={cn("flex w-full cursor-pointer items-center gap-2 px-2.5 py-2 text-sm", active?.id === org.id ? "text-foreground bg-secondary/60" : "text-muted-foreground hover:text-foreground hover:bg-secondary/50")}>
                {avatar(org.imageUrl, org.name)}
                <span className="truncate">{org.name}</span>
                {active?.id === org.id && <Icon name="check" className="ms-auto size-3.5" />}
              </button>
            ))}
            <div className="my-1 border-t border-border" />
            <button onClick={() => { setOpen(false); account.onCreateOrg(); }}
              className="flex w-full cursor-pointer items-center gap-2 px-2.5 py-2 text-sm text-muted-foreground hover:bg-secondary/50 hover:text-foreground">
              <span className="flex size-5 items-center justify-center text-base leading-none">+</span>
              {t("createOrg")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// Newly-appeared ids in a list, kept "fresh" briefly so additions stand out.
function useNewIds(ids: string[]) {
  const key = ids.join(",");
  const prev = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  useEffect(() => {
    const before = prev.current;
    prev.current = new Set(ids);
    if (!before) return;
    const added = ids.filter((i) => !before.has(i));
    if (!added.length) return;
    setFresh(new Set(added));
    const timer = setTimeout(() => setFresh(new Set()), 2500);
    return () => clearTimeout(timer);
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  return fresh;
}

function Row({ label, sub, control, onClick, danger, highlight }: {
  label: React.ReactNode;
  sub?: React.ReactNode;
  control?: React.ReactNode;
  onClick?: () => void;
  danger?: boolean;
  highlight?: boolean;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between gap-4 border-b border-border/60 py-3.5 text-start transition-colors duration-700 last:border-0",
        onClick && "cursor-pointer",
        danger ? "text-red-500" : "text-foreground",
        highlight && "-mx-2 rounded-lg border-transparent bg-accent/20 px-2",
      )}
    >
      <div className="min-w-0">
        <p className="text-sm">{label}</p>
        {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
      </div>
      {control && <div className="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground">{control}</div>}
    </Tag>
  );
}

// Bordered container that turns a run of Rows into a clearly-bounded list.
function ListCard({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-border bg-background/40 px-4">{children}</div>;
}

// Proper table for tabular data (members, invitations) — header row + grid columns.
function TableList({ cols, headers, rows }: {
  cols: string;
  headers?: React.ReactNode[];
  rows: { key: string; highlight?: boolean; cells: React.ReactNode[] }[];
}) {
  // Phones: header hidden, each row is a stacked card (first cell full-width,
  // the rest wrap beneath). ≥sm: a real grid aligned with the header row.
  return (
    <div className="overflow-hidden rounded-xl border border-border">
      {headers && (
        <div className={cn("hidden items-center gap-3 border-b border-border bg-secondary/50 px-4 py-2 sm:grid", cols)}>
          {headers.map((h, i) => <span key={i} className="truncate text-xs font-medium text-muted-foreground">{h}</span>)}
        </div>
      )}
      <div className="divide-y divide-border bg-background/40">
        {rows.length === 0 ? (
          <p className="px-4 py-4 text-center text-sm text-muted-foreground">—</p>
        ) : rows.map((r) => (
          <div key={r.key} className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3 transition-colors duration-700 sm:grid sm:gap-3", cols, r.highlight && "bg-accent/20")}>
            {r.cells.map((c, i) => <div key={i} className={cn("min-w-0 text-sm text-foreground", i === 0 && "w-full sm:w-auto")}>{c}</div>)}
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 mt-6 text-xs font-medium uppercase tracking-wide text-muted-foreground/70">{children}</p>;
}

function Segmented<T extends string>({ value, options, onChange }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex rounded-lg border border-border bg-secondary p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "cursor-pointer rounded-md px-3 py-1 text-xs transition-colors",
            value === o.value ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// Editable text: an always-bordered field, read-only until the pencil is
// clicked; the pencil becomes a check to save (Enter/blur also commit).
function EditableText({ value, onSave, dir, disabled }: {
  value: string;
  onSave: (v: string) => void;
  dir?: "ltr" | "rtl" | "auto";
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { setDraft(value); }, [value]);
  const commit = () => {
    setEditing(false);
    const v = draft.trim();
    if (v && v !== value) onSave(v);
    else setDraft(value);
  };
  return (
    <span className="flex items-center gap-1.5">
      <input
        ref={ref}
        value={draft}
        dir={dir}
        readOnly={!editing}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => editing && commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") { setDraft(value); setEditing(false); }
        }}
        className={cn(
          "w-full max-w-56 rounded-md border border-border px-2 py-1 text-end text-sm text-foreground focus:outline-none",
          editing ? "bg-background focus:ring-1 focus:ring-accent" : "cursor-default bg-transparent text-muted-foreground",
        )}
      />
      {!disabled && (
        <button
          onClick={() => {
            if (editing) commit();
            else { setEditing(true); requestAnimationFrame(() => { ref.current?.focus(); ref.current?.select(); }); }
          }}
          onMouseDown={(e) => e.preventDefault()}
          className="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary/80 hover:text-foreground"
          aria-label={editing ? t("save") : t("edit")}
        >
          {editing ? <Icon name="check" className="size-3.5" /> : (
            <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
            </svg>
          )}
        </button>
      )}
    </span>
  );
}

// Role picker — a dropdown, matching how access levels should be changed.
function RoleSelect({ value, options, onChange }: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs capitalize text-foreground transition-colors hover:bg-secondary/60"
      >
        {options.find((o) => o.value === value)?.label ?? value}
        <Icon name="chevron-down" className="size-3 text-muted-foreground" />
      </button>
      {open && (
        <DropdownMenu
          onClose={() => setOpen(false)}
          items={options.map((o) => ({ label: o.label, onClick: () => onChange(o.value) }))}
        />
      )}
    </div>
  );
}

// Destructive actions live in a bordered danger zone, as real buttons, each
// behind its own confirm (Challenge for deletes, ConfirmPair for the rest).
function DangerZone({ children }: { children: React.ReactNode }) {
  return (
    <>
      <SectionLabel>{t("dangerZone")}</SectionLabel>
      <div className="flex flex-col items-start gap-3 rounded-xl border border-red-500/25 p-4">{children}</div>
    </>
  );
}

function DangerButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="cursor-pointer rounded-lg border border-red-500/30 px-3.5 py-1.5 text-sm font-medium text-red-500 transition-colors hover:bg-red-500/10">
      {label}
    </button>
  );
}

// Small red pill for inline destructive actions (remove / revoke / disconnect).
function SmallDanger({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="cursor-pointer rounded-md border border-red-500/30 px-2 py-0.5 text-[11px] text-red-500 transition-colors hover:bg-red-500/10">
      {label}
    </button>
  );
}

function ConfirmPair({ prompt, onConfirm, onCancel, confirmLabel }: {
  prompt: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex w-full items-center justify-between gap-3">
      <p className="text-sm text-red-500">{prompt}</p>
      <span className="flex shrink-0 items-center gap-2">
        <button onClick={onCancel} className="cursor-pointer px-2 py-1 text-xs text-muted-foreground hover:text-foreground">{t("cancel")}</button>
        <button onClick={onConfirm} className="cursor-pointer rounded-md bg-red-500/10 px-3 py-1 text-xs font-medium text-red-500 hover:bg-red-500/20">{confirmLabel}</button>
      </span>
    </div>
  );
}

// Type-to-confirm challenge for destructive actions.
function Challenge({ prompt, expected, onConfirm, onCancel }: {
  prompt: string;
  expected: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  return (
    <div className="my-2 w-full rounded-xl border border-red-500/30 p-4">
      <p className="text-sm text-red-500">{prompt}</p>
      <input
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={expected}
        dir="ltr"
        className="mt-2 w-full rounded-md border border-border bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/40"
      />
      <div className="mt-2 flex justify-end gap-2">
        <button onClick={onCancel} className="cursor-pointer px-2 py-1 text-xs text-muted-foreground hover:text-foreground">{t("cancel")}</button>
        <button
          disabled={text.trim() !== expected}
          onClick={onConfirm}
          className="cursor-pointer rounded-md bg-red-500/10 px-3 py-1 text-xs font-medium text-red-500 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("delete")}
        </button>
      </div>
    </div>
  );
}

function GeneralTab() {
  const [mode, setMode] = useState<ThemeMode>(getThemeMode());
  return (
    <ListCard>
      <Row
        label={t("appearance")}
        control={
          <Segmented
            value={mode}
            options={[
              { value: "light", label: t("light") },
              { value: "dark", label: t("dark") },
              { value: "system", label: t("system") },
            ]}
            onChange={(m) => { setMode(m); setThemeMode(m, "settings"); }}
          />
        }
      />
      <Row
        label={t("languageLabel")}
        control={
          <Segmented
            value={getLang()}
            options={[{ value: "en" as const, label: "English" }, { value: "ar" as const, label: "العربية" }]}
            onChange={(l) => { setLang(l); track("language_changed", { to: l, source: "settings" }); }}
          />
        }
      />
    </ListCard>
  );
}

function AccountTab({ account }: { account: AccountInfo }) {
  const { user } = useUser();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [, bump] = useState(0);   // re-render after Clerk mutations resolve

  const changePhoto = async (f: File) => {
    try { await user?.setProfileImage({ file: f }); bump((n) => n + 1); } catch (e) { toast.error(clerkMsg(e)); }
  };
  const saveName = async (full: string) => {
    const [firstName, ...rest] = full.split(" ");
    try { await user?.update({ firstName, lastName: rest.join(" ") }); bump((n) => n + 1); } catch (e) { toast.error(clerkMsg(e)); }
  };

  return (
    <div>
      <div className="mb-8 flex items-center gap-5 border-b border-border/60 pb-6">
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && changePhoto(e.target.files[0])} />
        <button onClick={() => fileRef.current?.click()} className="group relative shrink-0 cursor-pointer" aria-label={t("edit")}>
          <div
            className="flex size-20 items-center justify-center rounded-full bg-secondary text-2xl font-medium text-foreground"
            style={user?.imageUrl ? { backgroundImage: `url(${user.imageUrl})`, backgroundSize: "cover" } : undefined}
          >
            {!user?.imageUrl && (account.user.name?.charAt(0) || account.user.email?.charAt(0) || "?")}
          </div>
          <div className="absolute bottom-0 end-0 flex size-6 items-center justify-center rounded-full border-2 border-background bg-secondary opacity-90 transition-opacity group-hover:opacity-100">
            <svg className="size-3 text-foreground" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
            </svg>
          </div>
        </button>
        <div className="min-w-0">
          <p className="truncate text-xl font-semibold tracking-tight text-foreground" dir="auto">{user?.fullName || account.user.name || account.user.email.split("@")[0]}</p>
          <p className="mt-1 truncate text-sm text-muted-foreground" dir="ltr">{account.user.email}</p>
        </div>
      </div>

      <ListCard>
        <Row label={t("name")} control={<EditableText value={user?.fullName || ""} onSave={saveName} dir="auto" />} />
      </ListCard>

      <SectionLabel>{t("emailAddresses")}</SectionLabel>
      <ListCard><EmailSection /></ListCard>

      <SectionLabel>{t("connectedAccounts")}</SectionLabel>
      <ListCard><ConnectedSection /></ListCard>

      <div className="mt-8">
        <DangerButton label={t("signOut")} onClick={account.onSignOut} />
      </div>
    </div>
  );
}

// Add / verify / set-primary / remove email addresses, all via the Clerk SDK.
function EmailSection() {
  const { user } = useUser();
  const toast = useToast();
  const [addOpen, setAddOpen] = useState(false);
  const [pending, setPending] = useState<{ emailAddress: string; attemptVerification: (p: { code: string }) => Promise<unknown> } | null>(null);
  const [code, setCode] = useState("");
  const [, bump] = useState(0);
  const refresh = () => bump((n) => n + 1);
  const freshEmails = useNewIds((user?.emailAddresses ?? []).map((e) => e.id));

  const createEmail = useReverification((email: string) => user!.createEmailAddress({ email }));
  const add = async (email: string) => {
    setAddOpen(false);
    try {
      const e = await createEmail(email);
      await e.prepareVerification({ strategy: "email_code" });
      setPending(e);
    } catch (e) { toast.error(clerkMsg(e)); }
  };
  const verify = async () => {
    try { await pending!.attemptVerification({ code }); setPending(null); setCode(""); refresh(); }
    catch (e) { toast.error(clerkMsg(e)); }
  };

  return (
    <>
      {(user?.emailAddresses ?? []).map((e) => {
        const primary = e.id === user?.primaryEmailAddressId;
        const verified = e.verification?.status === "verified";
        return (
          <Row
            key={e.id}
            highlight={freshEmails.has(e.id)}
            label={<span dir="ltr">{e.emailAddress}</span>}
            sub={primary ? t("primary") : !verified ? t("unverified") : undefined}
            control={!primary && (
              <span className="flex items-center gap-3 text-xs">
                {verified ? (
                  <button className="cursor-pointer hover:text-foreground" onClick={() => user?.update({ primaryEmailAddressId: e.id }).then(refresh).catch((err) => toast.error(clerkMsg(err)))}>
                    {t("makePrimary")}
                  </button>
                ) : (
                  // Re-send the code and reopen the code input for this address.
                  <button
                    className="cursor-pointer rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/60"
                    onClick={() => e.prepareVerification({ strategy: "email_code" }).then(() => setPending(e)).catch((err) => toast.error(clerkMsg(err)))}
                  >
                    {t("verify")}
                  </button>
                )}
                <SmallDanger label={t("remove")} onClick={() => e.destroy().then(refresh).catch((err) => toast.error(clerkMsg(err)))} />
              </span>
            )}
          />
        );
      })}
      {pending ? (
        <div className="flex items-center gap-2 py-3">
          <span className="text-xs text-muted-foreground">{t("enterCode")}</span>
          <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" dir="ltr"
            className="h-7 w-24 rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent" />
          <button onClick={verify} className="cursor-pointer text-xs font-medium text-foreground hover:opacity-80">{t("verify")}</button>
        </div>
      ) : addOpen ? (
        <div className="py-3"><InlineInput initial="" onSubmit={add} onCancel={() => setAddOpen(false)} /></div>
      ) : (
        <Row label={t("addEmail")} control={<span className="text-lg leading-none">+</span>} onClick={() => setAddOpen(true)} />
      )}
    </>
  );
}

function ProviderIcon({ provider }: { provider: string }) {
  const cls = "size-4 shrink-0 text-foreground";
  if (provider === "google") {
    return (
      <svg className="size-4 shrink-0" viewBox="0 0 24 24">
        <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z" />
        <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.31 7.31 24 12 24z" />
        <path fill="#FBBC05" d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z" />
        <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.69 1.29 6.62l3.98 3.09c.95-2.85 3.6-4.96 6.73-4.96z" />
      </svg>
    );
  }
  if (provider === "apple") {
    return (
      <svg className={cls} viewBox="0 0 24 24" fill="currentColor">
        <path d="M17.05 12.536c-.026-2.63 2.147-3.89 2.244-3.952-1.222-1.788-3.125-2.033-3.802-2.06-1.618-.164-3.158.953-3.979.953-.82 0-2.087-.93-3.43-.905-1.766.026-3.394 1.027-4.303 2.609-1.835 3.182-.469 7.898 1.319 10.483.873 1.266 1.914 2.688 3.281 2.637 1.317-.052 1.814-.852 3.406-.852 1.593 0 2.04.852 3.432.826 1.417-.026 2.313-1.291 3.181-2.562 1.001-1.47 1.413-2.892 1.437-2.965-.031-.014-2.758-1.058-2.786-4.212z" />
        <path d="M14.44 4.82c.726-.88 1.216-2.103 1.082-3.32-1.046.042-2.313.696-3.064 1.575-.673.779-1.262 2.023-1.104 3.216 1.167.09 2.36-.593 3.086-1.472z" />
      </svg>
    );
  }
  return (
    <svg className={cls} fill="none" stroke="currentColor" strokeWidth={1.6} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m-18.432 0A17.919 17.919 0 0112 16.5c3.162 0 6.133-.815 8.716-2.247m-18.432 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
    </svg>
  );
}

// Known providers always listed: connected ones can disconnect, the rest
// offer "+ Connect account" (OAuth redirect via the Clerk SDK).
const OAUTH_PROVIDERS = ["google", "apple"] as const;

function ConnectedSection() {
  const { user } = useUser();
  const toast = useToast();
  const [, bump] = useState(0);
  const accounts = user?.externalAccounts ?? [];
  const extras = accounts.filter((a) => !(OAUTH_PROVIDERS as readonly string[]).includes(a.provider.replace("oauth_", "")));

  // Sensitive action — Clerk may demand step-up verification; the hook opens
  // its reverification modal and retries transparently.
  const createExternal = useReverification((provider: string) =>
    user!.createExternalAccount({ strategy: `oauth_${provider}` as "oauth_google", redirectUrl: window.location.href }));

  const connect = async (provider: string) => {
    try {
      const res = await createExternal(provider);
      const url = res.verification?.externalVerificationRedirectURL;
      if (url) window.location.href = url.toString();
    } catch (e) { toast.error(clerkMsg(e)); }
  };

  const row = (provider: string, a?: (typeof accounts)[number]) => (
    <Row
      key={provider + (a?.id || "")}
      label={<span className="flex items-center gap-2.5"><ProviderIcon provider={provider} /><span className="capitalize">{provider}</span></span>}
      sub={a?.emailAddress ? <span dir="ltr">{a.emailAddress}</span> : undefined}
      control={a ? (
        <SmallDanger label={t("disconnect")} onClick={() => a.destroy().then(() => bump((n) => n + 1)).catch((e) => toast.error(clerkMsg(e)))} />
      ) : (
        <button onClick={() => connect(provider)} className="cursor-pointer rounded-lg border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/60">
          + {t("connect")}
        </button>
      )}
    />
  );

  return (
    <>
      {OAUTH_PROVIDERS.map((p) => row(p, accounts.find((a) => a.provider.replace("oauth_", "") === p)))}
      {extras.map((a) => row(a.provider.replace("oauth_", ""), a))}
    </>
  );
}

// Org context only: profile (name, slug, id), danger zone. Members have their own tab.
function OrganizationTab({ account, isAdmin }: { account: AccountInfo; isAdmin: boolean }) {
  const { organization, membership } = useOrganization();
  const toast = useToast();
  const logoRef = useRef<HTMLInputElement>(null);
  const [deleting, setDeleting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [, bump] = useState(0);

  if (!organization) return null;

  const setLogo = async (f: File) => {
    try { await organization.setLogo({ file: f }); bump((n) => n + 1); } catch (e) { toast.error(clerkMsg(e)); }
  };
  const save = (patch: { name?: string; slug?: string }) =>
    organization.update({ name: patch.name ?? organization.name, ...(patch.slug ? { slug: patch.slug } : {}) })
      .then(() => bump((n) => n + 1)).catch((e) => toast.error(clerkMsg(e)));

  return (
    <div>
      <div className="mb-8 flex items-center gap-5 border-b border-border/60 pb-6">
        <input ref={logoRef} type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && setLogo(e.target.files[0])} />
        <button onClick={isAdmin ? () => logoRef.current?.click() : undefined} className={cn("relative shrink-0", isAdmin && "group cursor-pointer")}>
          <div
            className="flex size-20 items-center justify-center rounded-2xl bg-secondary text-2xl font-medium text-foreground"
            style={organization.imageUrl ? { backgroundImage: `url(${organization.imageUrl})`, backgroundSize: "cover" } : undefined}
          >
            {!organization.imageUrl && organization.name.charAt(0)}
          </div>
          {isAdmin && (
            <div className="absolute bottom-0 end-0 flex size-6 items-center justify-center rounded-full border-2 border-background bg-secondary opacity-90 transition-opacity group-hover:opacity-100">
              <svg className="size-3 text-foreground" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
              </svg>
            </div>
          )}
        </button>
        <div className="min-w-0">
          <p className="truncate text-xl font-semibold tracking-tight text-foreground" dir="auto">{organization.name}</p>
          <p className="mt-1 truncate text-sm text-muted-foreground">{organization.membersCount} {t("members")}</p>
        </div>
      </div>

      <ListCard>
        <Row label={t("name")} control={<EditableText value={organization.name} onSave={(v) => save({ name: v })} dir="auto" disabled={!isAdmin} />} />
        <Row label={t("slug")} control={<EditableText value={organization.slug || ""} onSave={(v) => save({ slug: v })} dir="ltr" disabled={!isAdmin} />} />
        {membership?.createdAt && <Row label={t("joined")} control={fmtDate(membership.createdAt)} />}
      </ListCard>

      <DangerZone>
        {leaving ? (
          <ConfirmPair
            prompt={t("leaveOrgConfirm")}
            confirmLabel={t("leaveOrg")}
            onCancel={() => setLeaving(false)}
            onConfirm={() => membership?.destroy().then(() => account.onSwitchOrg(null)).catch((e) => { toast.error(clerkMsg(e)); setLeaving(false); })}
          />
        ) : (
          <DangerButton label={t("leaveOrg")} onClick={() => setLeaving(true)} />
        )}
        {isAdmin && (deleting ? (
          <Challenge
            prompt={t("typeNameToConfirm")}
            expected={organization.name}
            onCancel={() => setDeleting(false)}
            onConfirm={() => organization.destroy().then(() => account.onSwitchOrg(null)).catch((e) => { toast.error(clerkMsg(e)); setDeleting(false); })}
          />
        ) : (
          <DangerButton label={t("deleteOrg")} onClick={() => setDeleting(true)} />
        ))}
      </DangerZone>
    </div>
  );
}

// Standalone members tab: a real table with invitations alongside, like Clerk's.
function MembersTab({ isAdmin }: { isAdmin: boolean }) {
  const { organization, membership, memberships, invitations } = useOrganization({
    memberships: { infinite: true },
    invitations: { infinite: true },
  });
  const toast = useToast();
  const [mTab, setMTab] = useState<"members" | "invitations">("members");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteText, setInviteText] = useState("");
  const [inviteRole, setInviteRole] = useState("org:member");
  const [sending, setSending] = useState(false);
  const memberIds = (memberships?.data ?? []).map((m) => m.id);
  const inviteIds = (invitations?.data ?? []).map((i) => i.id);
  const freshMembers = useNewIds(memberIds);
  const freshInvites = useNewIds(inviteIds);

  if (!organization) return null;

  const roleOptions = [
    { value: "org:member", label: "member" },
    { value: "org:admin", label: "admin" },
  ];
  const revalidate = () => {
    (memberships as unknown as { revalidate?: () => void })?.revalidate?.();
    (invitations as unknown as { revalidate?: () => void })?.revalidate?.();
  };
  const sendInvites = async () => {
    const emails = inviteText.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    if (!emails.length) return;
    setSending(true);
    try {
      await organization.inviteMembers({ emailAddresses: emails, role: inviteRole });
      setInviteOpen(false); setInviteText(""); setMTab("invitations");
      revalidate();
    } catch (e) { toast.error(clerkMsg(e)); }
    finally { setSending(false); }
  };

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <Segmented
          value={mTab}
          options={[
            { value: "members" as const, label: `${t("members")} · ${memberships?.count ?? memberIds.length}` },
            { value: "invitations" as const, label: `${t("invitations")} · ${invitations?.count ?? inviteIds.length}` },
          ]}
          onChange={setMTab}
        />
        {isAdmin && (
          <button onClick={() => setInviteOpen((o) => !o)} className="cursor-pointer rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-85">
            {t("inviteMember")}
          </button>
        )}
      </div>

      {inviteOpen && isAdmin && (
        <div className="my-3 rounded-xl border border-border bg-background/40 p-4">
          <p className="mb-2 text-xs text-muted-foreground">{t("inviteHint")}</p>
          <textarea
            autoFocus
            value={inviteText}
            onChange={(e) => setInviteText(e.target.value)}
            placeholder="one@example.com, two@example.com"
            dir="ltr"
            rows={2}
            className="w-full resize-none rounded-md border border-border bg-transparent px-2.5 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground/40"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              {t("role")}
              <RoleSelect value={inviteRole} options={roleOptions} onChange={setInviteRole} />
            </span>
            <span className="flex items-center gap-2">
              <button onClick={() => setInviteOpen(false)} className="cursor-pointer px-2 py-1 text-xs text-muted-foreground hover:text-foreground">{t("cancel")}</button>
              <button onClick={sendInvites} disabled={sending || !inviteText.trim()} className="cursor-pointer rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">
                {sending ? t("saving") : t("sendInvitations")}
              </button>
            </span>
          </div>
        </div>
      )}

      {mTab === "members" ? (
        <TableList
          cols="grid-cols-[minmax(0,1fr)_7rem_7.5rem_5rem]"
          headers={[t("userCol"), t("joined"), t("role"), t("actions")]}
          rows={(memberships?.data ?? []).map((m) => {
            const u = m.publicUserData;
            const name = [u?.firstName, u?.lastName].filter(Boolean).join(" ") || u?.identifier || "";
            const self = m.id === membership?.id;
            return {
              key: m.id,
              highlight: freshMembers.has(m.id),
              cells: [
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-[10px] font-medium text-foreground"
                    style={u?.imageUrl ? { backgroundImage: `url(${u.imageUrl})`, backgroundSize: "cover" } : undefined}>
                    {!u?.imageUrl && name.charAt(0)}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate" dir="auto">{name}{self ? ` · ${t("thisDevice").replace(t("thisDevice"), "")}` : ""}</span>
                    {u?.identifier && <span className="block truncate text-xs text-muted-foreground" dir="ltr">{u.identifier}</span>}
                  </span>
                </span>,
                <span className="text-xs text-muted-foreground">{m.createdAt ? fmtDate(m.createdAt) : "—"}</span>,
                self || !isAdmin ? (
                  <span className="text-xs capitalize text-muted-foreground">{m.role.replace("org:", "")}</span>
                ) : (
                  <RoleSelect
                    value={m.role}
                    options={roleOptions}
                    onChange={(r) => m.update({ role: r }).then(revalidate).catch((e) => toast.error(clerkMsg(e)))}
                  />
                ),
                !self && isAdmin ? (
                  <SmallDanger label={t("remove")} onClick={() => m.destroy().then(revalidate).catch((e) => toast.error(clerkMsg(e)))} />
                ) : <span />,
              ],
            };
          })}
        />
      ) : (
        <TableList
          cols="grid-cols-[minmax(0,1fr)_7rem_7.5rem_5rem]"
          headers={[t("email"), t("invited"), t("role"), t("actions")]}
          rows={(invitations?.data ?? []).map((inv) => ({
            key: inv.id,
            highlight: freshInvites.has(inv.id),
            cells: [
              <span className="block truncate" dir="ltr">{inv.emailAddress}</span>,
              <span className="text-xs text-muted-foreground">{inv.createdAt ? fmtDate(inv.createdAt) : "—"}</span>,
              <span className="text-xs capitalize text-muted-foreground">{inv.role.replace("org:", "")}{inv.status ? ` · ${inv.status}` : ""}</span>,
              isAdmin ? <SmallDanger label={t("revoke")} onClick={() => inv.revoke().then(revalidate).catch((e) => toast.error(clerkMsg(e)))} /> : <span />,
            ],
          }))}
        />
      )}
    </div>
  );
}

// Workspace management only — switching happens in the navbar, not here.
// Members are shown with their org profile (avatar, name, email).
function WorkspacesTab({ ws }: { ws: WorkspacesMenu }) {
  const { memberships } = useOrganization({ memberships: { infinite: true } });
  const [manageId, setManageId] = useState<string | null>(null);
  const [members, setMembers] = useState<MemberInfo[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const freshWs = useNewIds(ws.items.map((w) => w.id));
  const freshMembers = useNewIds((members ?? []).map((m) => m.user_id));
  const managed = ws.items.find((w) => w.id === manageId) || null;
  const memberName = (id: string) => ws.orgMembers.find((m) => m.id === id)?.name || id;
  const infoOf = (uid: string) => {
    const u = (memberships?.data ?? []).find((m) => m.publicUserData?.userId === uid)?.publicUserData;
    return {
      name: u ? [u.firstName, u.lastName].filter(Boolean).join(" ") || u.identifier || uid : memberName(uid),
      email: u?.identifier,
      img: u?.imageUrl,
    };
  };
  const userChip = (uid: string) => {
    const u = infoOf(uid);
    return (
      <span className="flex min-w-0 items-center gap-2.5">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-[10px] font-medium text-foreground"
          style={u.img ? { backgroundImage: `url(${u.img})`, backgroundSize: "cover" } : undefined}>
          {!u.img && u.name.charAt(0)}
        </span>
        <span className="min-w-0">
          <span className="block truncate" dir="auto">{u.name}</span>
          {u.email && <span className="block truncate text-xs text-muted-foreground" dir="ltr">{u.email}</span>}
        </span>
      </span>
    );
  };

  useEffect(() => {
    if (!managed || managed.builtin) { setMembers(null); return; }
    let alive = true;
    setMembers(null);
    ws.fetchMembers(managed.id).then((m) => alive && setMembers(m)).catch(() => alive && setMembers([]));
    return () => { alive = false; };
  }, [managed?.id, managed?.builtin]);   // eslint-disable-line react-hooks/exhaustive-deps

  const refreshMembers = () => managed && ws.fetchMembers(managed.id).then(setMembers);

  if (managed) {
    const canDelete = managed.role === "owner" || ws.isOrgAdmin;
    return (
      <div>
        <button onClick={() => { setManageId(null); setDeleting(false); }} className="mb-3 flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <Icon name="chevron-left" className="size-3.5 rtl:rotate-180" />
          <span className="truncate">{managed.name}</span>
        </button>
        <SectionLabel>{t("members")}</SectionLabel>
        {managed.builtin ? (
          <p className="py-2 text-sm text-muted-foreground">{t("everyoneInOrg")}</p>
        ) : members === null ? <LoadingBar /> : (
          <>
            <ListCard>
              {members.map((m) => (
                <Row
                  key={m.user_id}
                  highlight={freshMembers.has(m.user_id)}
                  label={userChip(m.user_id)}
                  control={m.role === "owner" ? (
                    <span className="text-xs text-muted-foreground/60">{m.role}</span>
                  ) : (
                    <span className="flex items-center gap-3">
                      <RoleSelect
                        value={m.role}
                        options={[{ value: "editor", label: "editor" }, { value: "admin", label: "admin" }]}
                        onChange={(r) => ws.onSetMember(managed.id, m.user_id, r).then(refreshMembers)}
                      />
                      <SmallDanger label={t("remove")} onClick={() => ws.onRemoveMember(managed.id, m.user_id).then(refreshMembers)} />
                    </span>
                  )}
                />
              ))}
            </ListCard>
            {(() => {
              const outside = ws.orgMembers.filter((om) => !members.some((m) => m.user_id === om.id));
              if (!outside.length) return null;
              return (
                <>
                  <SectionLabel>{t("addMembers")}</SectionLabel>
                  <ListCard>
                    {outside.map((om) => (
                      <Row key={om.id} label={userChip(om.id)} control={<span className="text-lg leading-none">+</span>}
                        onClick={() => ws.onSetMember(managed.id, om.id, "editor").then(refreshMembers)} />
                    ))}
                  </ListCard>
                </>
              );
            })()}
          </>
        )}
        {canDelete && !managed.builtin && (
          <DangerZone>
            {deleting ? (
              <Challenge
                prompt={t("typeNameToConfirm")}
                expected={managed.name}
                onCancel={() => setDeleting(false)}
                onConfirm={() => {
                  const wasActive = ws.active?.id === managed.id;
                  ws.onDelete(managed.id).then(() => {
                    setManageId(null); setDeleting(false);
                    if (wasActive) ws.onSwitch(null);
                  });
                }}
              />
            ) : (
              <DangerButton label={t("deleteWorkspace")} onClick={() => setDeleting(true)} />
            )}
          </DangerZone>
        )}
      </div>
    );
  }

  return (
    <div>
      <ListCard>
        {ws.items.filter((w) => w.type === "team").map((w) => (
          <Row
            key={w.id}
            highlight={freshWs.has(w.id)}
            label={w.name}
            sub={w.role}
            control={(w.role === "owner" || w.role === "admin" || ws.isOrgAdmin) && (
              <button
                onClick={() => setManageId(w.id)}
                className="cursor-pointer rounded-lg border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/60"
              >
                {t("manage")}
              </button>
            )}
          />
        ))}
        {ws.canCreate && (creating ? (
          <div className="py-3"><InlineInput initial="" onSubmit={(name) => { setCreating(false); ws.onCreate(name); }} onCancel={() => setCreating(false)} /></div>
        ) : (
          <Row label={t("newWorkspace")} onClick={() => setCreating(true)} />
        ))}
      </ListCard>
    </div>
  );
}

const DeviceIcon = ({ mobile }: { mobile?: boolean }) => (
  <svg className="size-6 shrink-0 text-muted-foreground" fill="none" stroke="currentColor" strokeWidth={1.4} viewBox="0 0 24 24">
    {mobile
      ? <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3" />
      : <path strokeLinecap="round" strokeLinejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0V12a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 12V5.25" />}
  </svg>
);

// Password, active devices, and account deletion — Clerk SDK, no Clerk UI.
function SecurityTab() {
  const { user } = useUser();
  const clerk = useClerk();
  const toast = useToast();
  const [pwOpen, setPwOpen] = useState(false);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [signOutOthers, setSignOutOthers] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sessions, setSessions] = useState<{ id: string; lastActiveAt: Date; latestActivity?: { browserName?: string; browserVersion?: string; deviceType?: string; ipAddress?: string; city?: string; country?: string; isMobile?: boolean } | null; revoke: () => Promise<unknown> }[] | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const loadSessions = useCallback(() => {
    (user as unknown as { getSessions?: () => Promise<typeof sessions> })?.getSessions?.()
      .then((s) => setSessions(s ?? []))
      .catch(() => setSessions([]));
  }, [user]);
  useEffect(() => { loadSessions(); }, [loadSessions]);

  // Reverification stands in for the old password — Clerk's own UI does the same.
  const doUpdatePassword = useReverification((p: { newPassword: string; signOutOfOtherSessions?: boolean }) => user!.updatePassword(p));
  const doDelete = useReverification(() => user!.delete());
  const savePassword = async () => {
    if (next !== confirm) { toast.error(t("passwordMismatch")); return; }
    setSaving(true);
    try {
      await doUpdatePassword({ newPassword: next, signOutOfOtherSessions: signOutOthers });
      setPwOpen(false); setNext(""); setConfirm(""); setSignOutOthers(false);
    } catch (e) { toast.error(clerkMsg(e)); }
    finally { setSaving(false); }
  };

  const pwInput = "h-8 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent";
  return (
    <div>
      <SectionLabel>{t("password")}</SectionLabel>
      <ListCard>
        {pwOpen ? (
          <div className="flex max-w-sm flex-col gap-2 py-3">
            <input type="password" autoFocus value={next} onChange={(e) => setNext(e.target.value)} placeholder={t("newPassword")} className={pwInput} />
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={t("confirmPassword")} className={pwInput} />
            <label className="flex cursor-pointer items-center gap-2 py-1 text-xs text-muted-foreground">
              <input type="checkbox" checked={signOutOthers} onChange={(e) => setSignOutOthers(e.target.checked)} className="size-3.5 accent-foreground" />
              {t("signOutOtherDevices")}
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={() => setPwOpen(false)} className="cursor-pointer px-2 py-1 text-xs text-muted-foreground hover:text-foreground">{t("cancel")}</button>
              <button onClick={savePassword} disabled={!next || !confirm || saving} className="cursor-pointer rounded-lg bg-foreground px-3 py-1 text-xs font-medium text-background disabled:opacity-50">
                {saving ? t("saving") : t("save")}
              </button>
            </div>
          </div>
        ) : (
          <Row
            label={user?.passwordEnabled ? t("changePassword") : t("setPassword")}
            control={<Icon name="chevron-right" className="size-3.5 rtl:rotate-180" />}
            onClick={() => setPwOpen(true)}
          />
        )}
      </ListCard>

      <SectionLabel>{t("activeDevices")}</SectionLabel>
      {sessions === null ? <LoadingBar /> : (
        <ListCard>
          {sessions.map((s) => {
            const cur = s.id === clerk.session?.id;
            const a = s.latestActivity;
            return (
              <div key={s.id} className="flex items-start justify-between gap-4 border-b border-border/60 py-3.5 last:border-0">
                <div className="flex min-w-0 items-start gap-3">
                  <DeviceIcon mobile={a?.isMobile} />
                  <div className="min-w-0 text-sm text-foreground">
                    <p className="flex items-center gap-2 font-medium">
                      {a?.deviceType || "Device"}
                      {cur && <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{t("thisDevice")}</span>}
                    </p>
                    {(a?.browserName || a?.browserVersion) && (
                      <p className="mt-0.5 text-xs text-muted-foreground">{[a?.browserName, a?.browserVersion].filter(Boolean).join(" ")}</p>
                    )}
                    {(a?.ipAddress || a?.city) && (
                      <p className="mt-0.5 text-xs text-muted-foreground" dir="ltr">
                        {a?.ipAddress}{a?.city ? ` (${[a.city, a.country].filter(Boolean).join(", ")})` : ""}
                      </p>
                    )}
                    <p className="mt-0.5 text-xs text-muted-foreground">{fmtDateTime(s.lastActiveAt)}</p>
                  </div>
                </div>
                {!cur && <SmallDanger label={t("revoke")} onClick={() => s.revoke().then(loadSessions).catch((e) => toast.error(clerkMsg(e)))} />}
              </div>
            );
          })}
        </ListCard>
      )}

      <DangerZone>
        {confirmingDelete ? (
          <Challenge
            prompt={`${t("confirmDeleteAccount")} ${t("typeEmailToConfirm")}`}
            expected={user?.primaryEmailAddress?.emailAddress || ""}
            onCancel={() => setConfirmingDelete(false)}
            onConfirm={() => doDelete().then(() => { window.location.href = "/"; }).catch((e) => { toast.error(clerkMsg(e)); setConfirmingDelete(false); })}
          />
        ) : (
          <>
            <p className="text-xs text-muted-foreground">{t("deleteAccountNote")}</p>
            <DangerButton label={t("deleteAccount")} onClick={() => setConfirmingDelete(true)} />
          </>
        )}
      </DangerZone>
    </div>
  );
}

function HelpTab() {
  return (
    <ListCard>
      <Row label={t("about")} control={<Icon name="chevron-right" className="size-3.5 rtl:rotate-180" />} onClick={() => window.open("https://cycls.com", "_blank")} />
      <Row label={t("reportIssue")} onClick={() => supportMail(t("reportIssue"))} />
      <Row label={t("contactUs")} onClick={() => supportMail(t("contactUs"))} />
    </ListCard>
  );
}

// ---- Billing ----
// Data comes straight from Clerk's billing JS APIs (same plumbing as the Cycls
// cloud dashboard); every call is catch-safe so the tab degrades to just the
// plan card when billing isn't configured. Follows the context selector: in an
// org, everything is orgId-scoped.

type PaymentMethod = {
  id: string;
  cardType?: string;
  last4?: string;
  isDefault?: boolean;
  remove: (p?: { orgId?: string }) => Promise<unknown>;
  makeDefault: (p?: { orgId?: string }) => Promise<unknown>;
};

type SubItem = {
  id: string;
  plan?: { name?: string };
  status?: string;
  amount?: { currencySymbol: string; amountFormatted: string; amount?: number };
  planPeriod?: string;
  periodEnd?: Date | string | null;
  createdAt?: Date | string | null;
  cancel?: (p?: { orgId?: string }) => Promise<unknown>;
};

// Clerk's native drawers (checkout, subscription details) open above the
// settings via the z-index override in index.css, so settings stays open.
type Money = { currencySymbol?: string; amountFormatted?: string };
type Attempt = {
  id: string;
  status?: string;
  paidAt?: string | Date;
  updatedAt?: string | Date;
  amount?: Money;
  paymentSource?: { cardType?: string; last4?: string };
  subscriptionItems?: SubItem[];
};
type Statement = {
  id: string;
  timestamp: string | Date;
  status?: string;
  totals?: { grandTotal?: Money };
  groups?: { timestamp?: string | Date; items?: { id?: string; subscriptionItem?: SubItem; amount?: Money }[] }[];
};

function IdChip({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(id); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      className="mt-1 flex cursor-pointer items-center gap-1.5 font-mono text-xs text-muted-foreground hover:text-foreground"
      dir="ltr"
    >
      <Icon name={copied ? "check" : "copy"} className="size-3" />
      {id.length > 24 ? `${id.slice(0, 14)}…${id.slice(-5)}` : id}
    </button>
  );
}

const money = (a?: Money) => (a ? <span dir="ltr">{a.currencySymbol}{a.amountFormatted}</span> : null);

function BillingTab({ account }: { account: AccountInfo }) {
  const clerk = useClerk();
  const { organization } = useOrganization();
  const { user } = useUser();
  const toast = useToast();
  const [sub, setSub] = useState<{ subscriptionItems?: unknown[]; nextPayment?: { amount: { currencySymbol: string; amountFormatted: string }; date: string | Date } } | null>(null);
  const [statements, setStatements] = useState<unknown[]>([]);
  const [attempts, setAttempts] = useState<unknown[]>([]);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [hTab, setHTab] = useState<"payments" | "statements">("payments");
  const [showPlans, setShowPlans] = useState(false);   // in-place plan switcher, settings stays open
  const [detail, setDetail] = useState<{ kind: "statement" | "payment"; id: string } | null>(null);
  const freshMethods = useNewIds(methods.map((m) => m.id));
  const orgId = organization?.id;
  const payer = (organization ?? user) as unknown as { getPaymentMethods?: () => Promise<{ data?: PaymentMethod[] }> } | null;

  const load = useCallback(() => {
    const billing = (clerk as unknown as { billing?: {
      getSubscription?: (p: object) => Promise<unknown>;
      getStatements?: (p: object) => Promise<{ data?: unknown[] }>;
      getPaymentAttempts?: (p: object) => Promise<{ data?: unknown[] }>;
    } }).billing;
    Promise.all([
      billing?.getSubscription?.({ orgId }).catch(() => null) ?? null,
      billing?.getStatements?.({ orgId }).catch(() => ({ data: [] })) ?? { data: [] },
      billing?.getPaymentAttempts?.({ orgId }).catch(() => ({ data: [] })) ?? { data: [] },
      payer?.getPaymentMethods?.().catch(() => ({ data: [] })) ?? { data: [] },
    ]).then(([s, st, pa, pm]) => {
      setSub(s as typeof sub);
      setStatements((st as { data?: unknown[] })?.data ?? []);
      setAttempts((pa as { data?: unknown[] })?.data ?? []);
      setMethods((pm as { data?: PaymentMethod[] })?.data ?? []);
      setLoading(false);
    });
  }, [clerk, orgId, payer]);
  useEffect(() => { load(); }, [load]);

  const plan = account.plan;
  const items = (sub?.subscriptionItems ?? []) as SubItem[];
  const paid = items.filter((i) => (i.amount?.amount ?? 0) > 0);
  const shown = paid.length ? paid : items;

  const statusBadge = (status?: string) => status && (
    <span className={cn(
      "rounded-full px-2 py-0.5 text-[10px] font-medium capitalize",
      status === "failed" || status === "past_due" ? "bg-red-500/10 text-red-500" : "bg-secondary text-foreground",
    )}>
      {status.replace("_", " ")}
    </span>
  );

  if (showPlans) {
    return (
      <div>
        <button onClick={() => setShowPlans(false)} className="mb-3 flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <Icon name="chevron-left" className="size-3.5 rtl:rotate-180" />
          {t("billing")}
        </button>
        <PricingCards payerType={account.activeOrg ? "organization" : "user"} onSelect={() => setShowPlans(false)} />
      </div>
    );
  }

  // Drill-in detail page for a single payment or statement.
  if (detail) {
    const back = (label: string) => (
      <button onClick={() => setDetail(null)} className="mb-4 flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <Icon name="chevron-left" className="size-3.5 rtl:rotate-180" />
        {label}
      </button>
    );
    if (detail.kind === "payment") {
      const p = (attempts as Attempt[]).find((x) => x.id === detail.id);
      return (
        <div>
          {back(t("payments"))}
          {p && (
            <div className="overflow-hidden rounded-xl border border-border bg-background/40">
              <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-4">
                <div>
                  <p className="text-lg font-semibold text-foreground">{fmtDate(p.paidAt || p.updatedAt || new Date())}</p>
                  <IdChip id={p.id} />
                </div>
                {statusBadge(p.status)}
              </div>
              <div className="divide-y divide-border/60 px-4">
                {(p.subscriptionItems ?? []).map((si) => (
                  <div key={si.id} className="flex items-center justify-between py-3 text-sm text-foreground">
                    <span>{si.plan?.name || "—"}</span>
                    {money(si.amount)}
                  </div>
                ))}
                {p.paymentSource?.last4 && (
                  <div className="py-3 text-sm text-muted-foreground">
                    <span className="capitalize" dir="ltr">{p.paymentSource.cardType || "card"} •••• {p.paymentSource.last4}</span>
                  </div>
                )}
                <div className="flex items-center justify-between py-3 text-sm text-muted-foreground">
                  <span>{t("subtotal")}</span>
                  {money(p.amount)}
                </div>
              </div>
              <div className="flex items-center justify-between border-t border-border px-4 py-3.5 text-sm font-semibold text-foreground">
                <span>{t("totalDue")}</span>
                {money(p.amount)}
              </div>
            </div>
          )}
        </div>
      );
    }
    const s = (statements as Statement[]).find((x) => x.id === detail.id);
    return (
      <div>
        {back(t("statements"))}
        {s && (
          <div className="overflow-hidden rounded-xl border border-border bg-background/40">
            <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-4">
              <div>
                <p className="text-lg font-semibold text-foreground">
                  {new Date(s.timestamp).toLocaleDateString(dateLocale(), { month: "long", year: "numeric" })}
                </p>
                <IdChip id={s.id} />
              </div>
              {statusBadge(s.status)}
            </div>
            {(s.groups ?? []).map((g, gi) => (
              <div key={gi}>
                {g.timestamp && <p className="border-b border-border/60 bg-secondary/40 px-4 py-2 text-sm text-foreground">{fmtDate(g.timestamp)}</p>}
                <div className="divide-y divide-border/60 px-4">
                  {(g.items ?? []).map((it, ii) => (
                    <div key={it.id || ii} className="flex items-center justify-between py-3 text-sm text-foreground">
                      <span>
                        {it.subscriptionItem?.plan?.name || "—"}
                        {it.subscriptionItem?.amount && (
                          <span className="block text-xs text-muted-foreground" dir="ltr">
                            {it.subscriptionItem.amount.currencySymbol}{it.subscriptionItem.amount.amountFormatted}/{it.subscriptionItem.planPeriod === "annual" ? "yr" : "mo"}
                          </span>
                        )}
                      </span>
                      {money(it.amount)}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div className="flex items-center justify-between border-t border-border px-4 py-3.5 text-sm font-semibold text-foreground">
              <span>{t("totalPaid")}</span>
              {money(s.totals?.grandTotal)}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* Plan */}
      <SectionLabel>{t("currentPlan")}</SectionLabel>
      <div className="mb-4 rounded-xl border border-border bg-background/40 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="flex items-center gap-2 text-base font-semibold text-foreground">
              {plan?.name || shown[0]?.plan?.name || "Free"}
              {statusBadge(shown[0]?.status || plan?.status)}
            </p>
            {shown[0]?.amount && (
              <p className="mt-0.5 text-xs text-muted-foreground" dir="ltr">
                {shown[0].amount.currencySymbol}{shown[0].amount.amountFormatted}/{shown[0].planPeriod === "annual" ? "yr" : "mo"}
              </p>
            )}
            {shown[0]?.createdAt && (
              <p className="mt-1 text-xs text-muted-foreground">{t("subscribedOn")} {fmtDate(shown[0].createdAt)}</p>
            )}
            {sub?.nextPayment && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("nextPayment")} {fmtDate(sub.nextPayment.date)}
                {" · "}<span dir="ltr">{sub.nextPayment.amount.currencySymbol}{sub.nextPayment.amount.amountFormatted}</span>
              </p>
            )}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
            {shown.length > 0 && (
              // Clerk's native subscription drawer — details, invoices, cancel.
              <SubscriptionDetailsButton for={account.activeOrg ? "organization" : "user"}>
                <button className="cursor-pointer rounded-lg border border-border px-3.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-secondary/60">
                  {t("manageSubscription")}
                </button>
              </SubscriptionDetailsButton>
            )}
            <button onClick={() => setShowPlans(true)} className="cursor-pointer rounded-lg bg-foreground px-3.5 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-85">
              {t("switchPlan")}
            </button>
          </div>
        </div>
      </div>

      {loading ? <LoadingBar /> : (
        <>
          {/* Payment methods */}
          <SectionLabel>{t("paymentMethods")}</SectionLabel>
          {methods.length > 0 && <ListCard>
            {methods.map((m) => (
              <Row
                key={m.id}
                highlight={freshMethods.has(m.id)}
                label={<span className="capitalize" dir="ltr">{m.cardType || "card"} •••• {m.last4 || ""}</span>}
                sub={m.isDefault ? t("defaultLabel") : undefined}
                control={
                  <span className="flex items-center gap-3 text-xs">
                    {!m.isDefault && (
                      <button className="cursor-pointer hover:text-foreground" onClick={() => m.makeDefault({ orgId }).then(load).catch((e) => toast.error(clerkMsg(e)))}>{t("setDefault")}</button>
                    )}
                    <SmallDanger label={t("remove")} onClick={() => m.remove({ orgId }).then(load).catch((e) => toast.error(clerkMsg(e)))} />
                  </span>
                }
              />
            ))}
          </ListCard>}
          {adding ? (
            <AddCard forOrg={!!organization} onDone={() => { setAdding(false); load(); }} onCancel={() => setAdding(false)} />
          ) : (
            <button onClick={() => setAdding(true)} className="mt-2 flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed border-border py-2.5 text-sm text-muted-foreground transition-colors hover:bg-secondary/40 hover:text-foreground">
              <span className="text-base leading-none">+</span> {t("addPaymentMethod")}
            </button>
          )}

          {/* Payments (individual charges, with status) | Statements (receipts) */}
          <div className="mt-6 mb-2">
            <Segmented
              value={hTab}
              options={[{ value: "payments" as const, label: t("payments") }, { value: "statements" as const, label: t("statements") }]}
              onChange={setHTab}
            />
          </div>
          {hTab === "payments" ? (
            <ListCard>
              {attempts.length === 0 ? (
                <p className="py-3 text-sm text-muted-foreground">—</p>
              ) : (attempts as Attempt[]).map((p) => (
                <Row
                  key={p.id}
                  onClick={() => setDetail({ kind: "payment", id: p.id })}
                  label={new Date(p.paidAt || p.updatedAt || Date.now()).toLocaleDateString(dateLocale(), { month: "short", day: "numeric", year: "numeric" })}
                  sub={p.paymentSource?.last4 ? <span dir="ltr">{p.paymentSource.cardType || "card"} •••• {p.paymentSource.last4}</span> : undefined}
                  control={
                    <span className="flex items-center gap-2.5">
                      {statusBadge(p.status)}
                      {money(p.amount)}
                      <Icon name="chevron-right" className="size-3.5 rtl:rotate-180" />
                    </span>
                  }
                />
              ))}
            </ListCard>
          ) : (
            <ListCard>
              {statements.length === 0 ? (
                <p className="py-3 text-sm text-muted-foreground">{t("noStatements")}</p>
              ) : (statements as Statement[]).map((s) => (
                <Row
                  key={s.id}
                  onClick={() => setDetail({ kind: "statement", id: s.id })}
                  label={new Date(s.timestamp).toLocaleDateString(dateLocale(), { month: "long", year: "numeric" })}
                  sub={s.status}
                  control={
                    <span className="flex items-center gap-2.5">
                      {money(s.totals?.grandTotal)}
                      <Icon name="chevron-right" className="size-3.5 rtl:rotate-180" />
                    </span>
                  }
                />
              ))}
            </ListCard>
          )}
        </>
      )}
    </div>
  );
}

function AddCard({ forOrg, onDone, onCancel }: { forOrg: boolean; onDone: () => void; onCancel: () => void }) {
  const dark = useDarkMode();
  return (
    <div className="my-2 rounded-xl border border-border p-4">
      <PaymentElementProvider
        for={forOrg ? "organization" : "user"}
        stripeAppearance={{
          colorPrimary: dark ? "#ffffff" : "#0a0a0a",
          colorBackground: dark ? "#141414" : "#ffffff",
          colorText: dark ? "#e0e0e0" : "#0a0a0a",
          colorTextSecondary: dark ? "#a3a3a3" : "#737373",
          colorSuccess: dark ? "#4ade80" : "#16a34a",
          colorDanger: dark ? "#f87171" : "#dc2626",
          colorWarning: dark ? "#fbbf24" : "#d97706",
          fontWeightNormal: "400",
          fontWeightMedium: "500",
          fontWeightBold: "600",
          fontSizeXl: "16px",
          fontSizeLg: "14px",
          fontSizeSm: "13px",
          fontSizeXs: "12px",
          borderRadius: "8px",
          spacingUnit: "4px",
        }}
      >
        <AddCardForm onDone={onDone} onCancel={onCancel} />
      </PaymentElementProvider>
    </div>
  );
}

function AddCardForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { submit, isFormReady } = usePaymentElement();
  const { organization } = useOrganization();
  const { user } = useUser();
  const toast = useToast();
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const result = await submit();
      if (result.error) { toast.error(result.error.error?.message || "Failed"); return; }
      const payer = (organization ?? user) as unknown as { addPaymentMethod: (p: { gateway: string; paymentToken: string }) => Promise<unknown> };
      await payer.addPaymentMethod({ gateway: "stripe", paymentToken: result.data.paymentToken });
      onDone();
    } catch (e) {
      toast.error((e as { errors?: { message?: string }[] })?.errors?.[0]?.message || "Failed to add payment method");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PaymentElement fallback={<LoadingBar />} />
      <div className="mt-3 flex justify-end gap-2">
        <button onClick={onCancel} className="cursor-pointer px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">{t("cancel")}</button>
        <button onClick={save} disabled={!isFormReady || saving} className="cursor-pointer rounded-lg bg-foreground px-3.5 py-1.5 text-xs font-medium text-background disabled:opacity-50">
          {saving ? t("saving") : t("addCard")}
        </button>
      </div>
    </div>
  );
}
