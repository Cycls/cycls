import type { ReactNode } from "react";
import { Languages, Moon, Sun } from "lucide-react";
import { useLang } from "../i18n";
import { useKitT } from "../strings";
import { useTheme } from "./theme";
import { Button } from "../ui/button";
import { cn } from "../lib/utils";

export function LangToggle() {
  const { lang, setLang } = useLang();
  const t = useKitT();
  const next = lang === "ar" ? "en" : "ar";
  const label = next === "ar" ? t("switchToAr") : t("switchToEn");
  return (
    <Button variant="ghost" size="icon" aria-label={`${t("language")}: ${label}`} title={label} onClick={() => setLang(next)}>
      <Languages />
    </Button>
  );
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const t = useKitT();
  return (
    <Button variant="ghost" size="icon" aria-label={`${t("theme")}: ${theme === "dark" ? t("dark") : t("light")}`}
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
      {theme === "dark" ? <Moon /> : <Sun />}
    </Button>
  );
}

/** The app's header row: icon + title (+ subtitle) at the start, actions and the two
 *  toggles at the end. Nothing is truncated: the title wraps (balanced), the subtitle
 *  shows up to 2 lines (the full text is its title attribute), and when the actions do not
 *  fit beside a 7rem title block they wrap onto their own row. At 360 px keep ≤ 2 icon
 *  actions here and put the rest in a DropdownMenu. */
export function Toolbar({ icon, title, subtitle, actions, className }: {
  icon?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; className?: string;
}) {
  return (
    <header className={cn("sticky top-0 z-30 border-b border-border bg-card", className)}>
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-2 gap-y-2 px-3 py-2 sm:px-4">
        {icon && <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary [&_svg]:size-5" aria-hidden>{icon}</div>}
        <div className="min-w-0 flex-1 basis-28">
          <h1 className="text-balance break-words text-base font-semibold leading-tight">{title}</h1>
          {subtitle && <p className="line-clamp-2 break-words text-xs text-muted-foreground" title={typeof subtitle === "string" ? subtitle : undefined}>{subtitle}</p>}
        </div>
        <div className="ms-auto flex flex-wrap items-center justify-end gap-1">
          {actions}
          <LangToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
