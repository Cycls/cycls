import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { track } from "./analytics";

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

// Suggested follow-up chip (the agent's `suggest` tool). Per-device
// preference; a window event keeps the open chat in sync with settings.
const FOLLOWUPS_KEY = "cycls_followups";

export const followUpsEnabled = () => {
  try { return localStorage.getItem(FOLLOWUPS_KEY) !== "off"; } catch { return true; }
};

export function setFollowUpsEnabled(on: boolean, source: string) {
  localStorage.setItem(FOLLOWUPS_KEY, on ? "on" : "off");
  window.dispatchEvent(new Event("followupschange"));
  track("followups_toggled", { to: on, source });
}

// Clarifying-question card (the agent's `ask` tool). Off hides the card, not
// the question: the step line still names it and typing a reply still answers.
const ASK_KEY = "cycls_ask";

export const askEnabled = () => {
  try { return localStorage.getItem(ASK_KEY) !== "off"; } catch { return true; }
};

// Web search, per person. Off rides the request as disabled_tools and the
// server drops the tool for the turn; it can't enable a tool the agent lacks.
const WEB_SEARCH_KEY = "cycls_web_search";

export const webSearchEnabled = () => {
  try { return localStorage.getItem(WEB_SEARCH_KEY) !== "off"; } catch { return true; }
};

export function setWebSearchEnabled(on: boolean, source: string) {
  localStorage.setItem(WEB_SEARCH_KEY, on ? "on" : "off");
  track("web_search_toggled", { to: on, source });
}

export function setAskEnabled(on: boolean, source: string) {
  localStorage.setItem(ASK_KEY, on ? "on" : "off");
  window.dispatchEvent(new Event("askchange"));
  track("ask_toggled", { to: on, source });
}
