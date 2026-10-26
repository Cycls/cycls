import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { cycls, getView, setView, useCycls, wearHostTokens, type HostTokens } from "../cycls";

export type Theme = "light" | "dark";
interface ThemeState { theme: Theme; resolvedTheme: Theme; setTheme: (t: Theme) => void }
const C = createContext<ThemeState | null>(null);

function system(): Theme {
  try { return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; } catch { return "light"; }
}

/** Drop-in for next-themes' useTheme() (shadcn's sonner.tsx and blocks import it;
 *  shadcn-fix rewrites "next-themes" to this file).
 *  ctx.theme from the host, else the OS; a manual toggle wins and survives the refresh. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { theme: hostTheme, pending } = useCycls();
  const [chosen, setChosen] = useState<Theme | null>(() => getView<Theme | null>("kit:theme", null));
  const [sys, setSys] = useState<Theme>(system);
  useEffect(() => {
    let mq: MediaQueryList;
    try { mq = matchMedia("(prefers-color-scheme: dark)"); } catch { return; }
    const f = () => setSys(mq.matches ? "dark" : "light");
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  // The host pushes {type: "theme", theme, tokens} when the workspace's app theme or its own light/dark
  // changes (docs/notes/apps.md, "The theme"): follow its mode live, as the colors already are.
  const { ctx } = useCycls();
  const [pushed, setPushed] = useState<Theme | null>(null);
  useEffect(() => { wearHostTokens(ctx?.tokens); }, [ctx]);
  useEffect(() => {
    const on = cycls()?.onCommand;
    if (typeof on !== "function") return;
    return on((c) => {
      if (c?.type !== "theme") return;
      if (c.theme === "dark" || c.theme === "light") setPushed(c.theme);
      wearHostTokens((c.tokens as HostTokens | null) ?? null);
    });
  }, []);
  const theme: Theme = chosen ?? pushed ?? hostTheme ?? sys;
  useEffect(() => {
    if (pending && !chosen) return;    // the OS-following CSS holds until the host has spoken
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme === "dark");   // shadcn's convention
    setView("kit:theme-boot", theme);
  }, [theme, pending, chosen]);
  const setTheme = useCallback((t: Theme) => { setChosen(t); setView("kit:theme", t); }, []);
  const value = useMemo(() => ({ theme, resolvedTheme: theme, setTheme }), [theme, setTheme]);
  return createElement(C.Provider, { value }, children);
}

export function useTheme(): ThemeState {
  const v = useContext(C);
  if (!v) throw new Error("useTheme() needs <ThemeProvider> (AppShell includes it)");
  return v;
}
