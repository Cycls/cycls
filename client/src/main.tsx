import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initPostHog, setAgentDomain } from "./lib/posthog";
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
const inlinedConfig = (window as unknown as { __CONFIG__?: { analytics?: boolean; name?: string } }).__CONFIG__;
if (inlinedConfig?.analytics) {
  initPostHog();
  setAgentDomain(inlinedConfig.name);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
);
