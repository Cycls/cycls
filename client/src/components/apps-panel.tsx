import { useRef, useState } from "react";
import { AppTile } from "./app-icon";
import { LoadingBar } from "./loading-bar";
import { ContextMenu, InlineInput } from "./files";
import { EmojiPicker } from "./emoji-picker";
import { Icon } from "./icon";
import { t } from "../lib/i18n";
import type { AppInfo } from "../hooks/use-apps";

export function AppsPanel({ apps, loading, onOpen, onRename, onSetIcon, onUploadIcon, onDelete }: {
  apps: AppInfo[];
  loading: boolean;
  onOpen: (app: AppInfo) => void;
  onRename?: (app: AppInfo, name: string) => void;
  onSetIcon?: (app: AppInfo, icon: string) => void;
  onUploadIcon?: (app: AppInfo, file: File) => void;
  onDelete?: (app: AppInfo) => void;   // admins only — the server enforces it too
}) {
  const [menu, setMenu] = useState<{ x: number; y: number; app: AppInfo } | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [iconFor, setIconFor] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadFor = useRef<AppInfo | null>(null);
  if (loading) return <LoadingBar />;
  const itemsFor = (app: AppInfo) => [
    ...(onRename ? [{ label: t("rename"), onClick: () => setRenaming(app.slug) }] : []),
    ...(onSetIcon ? [{ label: t("changeIcon"), onClick: () => setIconFor(app.slug) }] : []),
    ...(onUploadIcon ? [{ label: t("uploadIcon"), onClick: () => { uploadFor.current = app; fileInput.current?.click(); } }] : []),
    ...(onDelete ? [{ label: t("delete"), danger: true, divider: true,
                      onClick: () => { if (confirm(t("deleteAppConfirm").replace("{name}", app.name))) onDelete(app); } }] : []),
  ];

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
      <div className="flex-1 overflow-y-auto pb-20">
        {apps.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-16 text-center">
            <Icon name="folder" className="size-8 text-muted-foreground" strokeWidth={1.5} />
            <p className="text-sm font-medium">{t("noApps")}</p>
            <p className="text-xs text-muted-foreground">{t("noAppsSub")}</p>
          </div>
        ) : (
          // A phone's home screen: an app opens on a click, its menu on a right-click, what it does on hover
          <div className="grid grid-cols-3 gap-x-2 gap-y-5 px-3 py-5">
            {apps.map((app, i) => (
              <div
                key={app.slug}
                role="button"
                onClick={() => { if (!renaming && !iconFor) onOpen(app); }}
                onContextMenu={(e) => { if (!itemsFor(app).length) return; e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, app }); }}
                className="group relative flex cursor-pointer flex-col items-center gap-1.5 px-1"
              >
                <span className="relative">
                  <AppTile app={app} className="size-14 transition-transform group-hover:scale-105" textClassName="text-3xl" />
                  {iconFor === app.slug && onSetIcon && (
                    <span onClick={(e) => e.stopPropagation()}>
                      <EmojiPicker
                        align="start"
                        onPick={(e) => { setIconFor(null); onSetIcon(app, e); }}
                        onClear={app.icon ? () => { setIconFor(null); onSetIcon(app, ""); } : undefined}
                        onClose={() => setIconFor(null)}
                      />
                    </span>
                  )}
                </span>
                {renaming === app.slug && onRename ? (
                  <span className="w-full" onClick={(e) => e.stopPropagation()}>
                    <InlineInput
                      initial={app.name}
                      onSubmit={(v) => { setRenaming(null); if (v.trim() && v.trim() !== app.name) onRename(app, v.trim()); }}
                      onCancel={() => setRenaming(null)}
                    />
                  </span>
                ) : (
                  <span dir="auto" className="line-clamp-2 w-full text-center text-xs leading-4 text-foreground">{app.name}</span>
                )}
                {/* under its icon, kept inside the panel: the first column's flush left, the last's flush right */}
                {app.description && renaming !== app.slug && (
                  <span dir="auto" className={`pointer-events-none absolute top-full z-20 mt-1.5 w-52 rounded-xl border border-white/40 bg-background/60 p-3 text-start text-xs leading-5 text-foreground opacity-0 shadow-lg backdrop-blur-xl backdrop-saturate-150 transition-opacity delay-0 group-hover:opacity-100 group-hover:delay-300 dark:border-white/10 ${["left-0", "left-1/2 -translate-x-1/2", "right-0"][i % 3]}`}>
                    {app.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {menu && <ContextMenu x={menu.x} y={menu.y} items={itemsFor(menu.app)} onClose={() => setMenu(null)} />}
    </div>
  );
}
