import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { track } from "./posthog";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type ThemeMode = "light" | "dark" | "system";
const THEME_KEY = "cycls_theme";

export const getThemeMode = (): ThemeMode => {
  const v = localStorage.getItem(THEME_KEY);
  return v === "light" || v === "dark" ? v : "system";
};

export function applyTheme() {
  const mode = getThemeMode();
  const dark = mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.body.classList.toggle("dark", dark);
}

export function setThemeMode(mode: ThemeMode, source: string) {
  localStorage.setItem(THEME_KEY, mode);
  applyTheme();
  track("theme_changed", { to: mode, source });
}

export function toggleDark(source: string) {
  setThemeMode(document.body.classList.contains("dark") ? "light" : "dark", source);
}
