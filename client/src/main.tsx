import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initAnalytics, setAgentDomain, type ProviderSpec } from "./lib/posthog";
import { ToastProvider } from "./lib/toast";
import { applyTheme, getThemeMode } from "./lib/utils";

applyTheme();
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (getThemeMode() === "system") applyTheme();
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
      <App />
    </ToastProvider>
  </StrictMode>,
);
