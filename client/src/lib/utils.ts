import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { track } from "./posthog";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function toggleDark(source: string) {
  document.body.classList.toggle("dark");
  track("theme_changed", {
    to: document.body.classList.contains("dark") ? "dark" : "light",
    source,
  });
}
