import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initPostHog, setAgentDomain } from "./lib/posthog";

// Default to system preferences
if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
  document.body.classList.add("dark");
}
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
    <App />
  </StrictMode>,
);
