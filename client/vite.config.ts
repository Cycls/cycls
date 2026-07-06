import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = "http://localhost:8080";
const apis = ["/config", "/chat", "/chats", "/sessions", "/files", "/shared-assets", "/transcribe", "/workspaces"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../cycls/agent/web/themes/default", emptyOutDir: true },
  server: {
    proxy: {
      ...Object.fromEntries(apis.map((p) => [p, backend])),
      "/share": { target: backend, bypass: (r) => r.url?.startsWith("/shared/") ? "/index.html" : undefined },
    },
  },
});
