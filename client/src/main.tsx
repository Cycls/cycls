import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initAnalytics, setAgentDomain, type ProviderSpec } from "./lib/analytics";
import { ToastProvider } from "./lib/toast";
import { ErrorBoundary } from "./components/error-boundary";
import { applyTheme, getThemeMode } from "./lib/utils";

applyTheme();
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (getThemeMode() === "system") applyTheme();
});
// A deploy renames the lazy-loaded chunks, so a tab opened before it asks for files that are gone: reload once into
// the new build rather than show an error. The stamp stops a loop if the chunk is missing for some other reason.
window.addEventListener("vite:preloadError", (e) => {
  if (Date.now() - Number(sessionStorage.getItem("cycls_chunk_reload") || 0) < 10_000) return;
  sessionStorage.setItem("cycls_chunk_reload", String(Date.now()));
  e.preventDefault();
  location.reload();
});
if (navigator.language.startsWith("ar")) {
  document.documentElement.lang = "ar";
  document.documentElement.dir = "rtl";
}

// Initialize analytics synchronously so share page visits are captured
// before the SharedView fetch resolves.
const inlinedConfig = (window as unknown as { __CONFIG__?: { analytics?: ProviderSpec[] | null; name?: string } }).__CONFIG__;
if (inlinedConfig?.analytics?.length) {
  initAnalytics(inlinedConfig.analytics);
  setAgentDomain(inlinedConfig.name);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </ToastProvider>
  </StrictMode>,
);
