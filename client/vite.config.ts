import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { META, srcHash } from "./scripts/src-hash.mjs";

// What the bundle was built from, for CI's staleness check (scripts/src-hash.mjs).
const stampSources = {
  name: "cycls-src-hash",
  transformIndexHtml: (html: string) => html.replace("</head>", `  <meta name="${META}" content="${srcHash()}" />\n  </head>`),
};

const backend = process.env.CYCLS_BACKEND || "http://localhost:8080";
const apis = ["/config", "/explore", "/chat", "/chats", "/sessions", "/files", "/shared-assets", "/transcribe", "/workspaces", "/connectors"];

export default defineConfig({
  plugins: [react(), tailwindcss(), stampSources],
  build: { outDir: "../cycls/_agent/web/themes/default", emptyOutDir: true },
  server: {
    proxy: {
      ...Object.fromEntries(apis.map((p) => [p, backend])),
      "/share": { target: backend, bypass: (r) => r.url?.startsWith("/shared/") ? "/index.html" : undefined },
    },
  },
});
