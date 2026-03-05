import { useSyncExternalStore } from "react";

function subscribe(callback: () => void) {
  const observer = new MutationObserver(callback);
  observer.observe(document.body, {
    attributes: true,
    attributeFilter: ["class"],
  });
  return () => observer.disconnect();
}

function getSnapshot() {
  return document.body.classList.contains("dark");
}

export function useDarkMode() {
  return useSyncExternalStore(subscribe, getSnapshot);
}
