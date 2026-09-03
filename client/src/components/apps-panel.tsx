import { Icon } from "./icon";
import { AppIcon } from "./app-icon";
import { LoadingBar } from "./loading-bar";
import { t } from "../lib/i18n";
import type { AppInfo } from "../hooks/use-apps";

export function AppsPanel({ apps, loading, onOpen }: {
  apps: AppInfo[];
  loading: boolean;
  onOpen: (app: AppInfo) => void;
}) {
  if (loading) return <LoadingBar />;

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {apps.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-16 text-center">
            <Icon name="folder" className="size-8 text-muted-foreground" strokeWidth={1.5} />
            <p className="text-sm font-medium">{t("noApps")}</p>
            <p className="text-xs text-muted-foreground">{t("noAppsSub")}</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {apps.map((app) => (
              <button
                key={app.slug}
                onClick={() => onOpen(app)}
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-foreground/25"
              >
                <span className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary text-lg">
                  <AppIcon app={app} className="size-full" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{app.name}</span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {app.description ?? app.slug}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
