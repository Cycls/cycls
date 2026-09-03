import { useRef, useState } from "react";
import { AppIcon } from "./app-icon";
import { LoadingBar } from "./loading-bar";
import { DropdownMenu, InlineInput } from "./files";
import { EmojiPicker } from "./emoji-picker";
import { Icon } from "./icon";
import { t } from "../lib/i18n";
import type { AppInfo } from "../hooks/use-apps";

export function AppsPanel({ apps, loading, onOpen, onOpenInTab, onRename, onSetIcon, onUploadIcon, onDelete }: {
  apps: AppInfo[];
  loading: boolean;
  onOpen: (app: AppInfo) => void;
  onOpenInTab?: (app: AppInfo) => void;
  onRename?: (app: AppInfo, name: string) => void;
  onSetIcon?: (app: AppInfo, icon: string) => void;
  onUploadIcon?: (app: AppInfo, file: File) => void;
  onDelete?: (app: AppInfo) => void;   // admins only — the server enforces it too
}) {
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [iconFor, setIconFor] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadFor = useRef<AppInfo | null>(null);
  if (loading) return <LoadingBar />;

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <input
        ref={fileInput} type="file" accept="image/*" className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]; const app = uploadFor.current;
          e.target.value = "";
          if (f && app && onUploadIcon) onUploadIcon(app, f);
        }}
      />
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {apps.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-16 text-center">
            <Icon name="folder" className="size-8 text-muted-foreground" strokeWidth={1.5} />
            <p className="text-sm font-medium">{t("noApps")}</p>
            <p className="text-xs text-muted-foreground">{t("noAppsSub")}</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {apps.map((app) => {
              const items = [
                ...(onOpenInTab ? [{ label: t("openInTab"), onClick: () => onOpenInTab(app) }] : []),
                ...(onRename ? [{ label: t("rename"), onClick: () => setRenaming(app.slug) }] : []),
                ...(onSetIcon ? [{ label: t("changeIcon"), onClick: () => setIconFor(app.slug) }] : []),
                ...(onUploadIcon ? [{ label: t("uploadIcon"), onClick: () => { uploadFor.current = app; fileInput.current?.click(); } }] : []),
                ...(onDelete ? [{ label: t("delete"), danger: true, divider: true,
                                  onClick: () => { if (confirm(t("deleteAppConfirm").replace("{name}", app.name))) onDelete(app); } }] : []),
              ];
              return (
                <div
                  key={app.slug}
                  role="button"
                  onClick={() => { if (!renaming && !iconFor) onOpen(app); }}
                  className="group relative flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-card p-4 text-start transition-colors hover:border-foreground/25"
                >
                  <span className="relative shrink-0" onClick={(e) => e.stopPropagation()}>
                    <span className="flex size-9 items-center justify-center overflow-hidden rounded-lg bg-secondary text-lg">
                      <AppIcon app={app} className="size-full" />
                    </span>
                    {iconFor === app.slug && onSetIcon && (
                      <EmojiPicker
                        align="start"
                        onPick={(e) => { setIconFor(null); onSetIcon(app, e); }}
                        onClear={app.icon ? () => { setIconFor(null); onSetIcon(app, ""); } : undefined}
                        onClose={() => setIconFor(null)}
                      />
                    )}
                  </span>
                  <span className="min-w-0 flex-1 pe-6">
                    {renaming === app.slug && onRename ? (
                      <span onClick={(e) => e.stopPropagation()}>
                        <InlineInput
                          initial={app.name}
                          onSubmit={(v) => { setRenaming(null); if (v.trim() && v.trim() !== app.name) onRename(app, v.trim()); }}
                          onCancel={() => setRenaming(null)}
                        />
                      </span>
                    ) : (
                      <span className="block truncate text-sm font-medium">{app.name}</span>
                    )}
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {app.description ?? app.slug}
                    </span>
                  </span>
                  {items.length > 0 && (
                    <span className="absolute end-2 top-2" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => setMenuFor(menuFor === app.slug ? null : app.slug)}
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground opacity-100 transition-opacity hover:bg-secondary hover:text-foreground sm:opacity-0 sm:group-hover:opacity-100 cursor-pointer"
                        aria-label={t("more")} title={t("more")}
                      >
                        <svg className="size-4" fill="currentColor" viewBox="0 0 24 24">
                          <circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" />
                        </svg>
                      </button>
                      {menuFor === app.slug && <DropdownMenu items={items} onClose={() => setMenuFor(null)} />}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
