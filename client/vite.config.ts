import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = "http://localhost:8080";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../cycls/agent/web/themes/default",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      ...Object.fromEntries(
        ["/config", "/chat", "/sessions", "/files", "/shared-assets", "/transcribe"].map(
          (p) => [p, backend]
        )
      ),
      // /share/<user>/<token> is the SPA route (serve index.html);
      // sub-paths (/data, /file/...) and bare /share owner ops go to backend.
      "/share": {
        target: backend,
        bypass: (req) => /^\/share\/[^/]+\/[^/]+$/.test(req.url ?? "") ? "/index.html" : undefined,
      },
    },
  },
});
