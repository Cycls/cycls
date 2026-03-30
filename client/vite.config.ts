import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = "http://localhost:8080";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../cycls/app/themes/default",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      ...Object.fromEntries(
        ["/config", "/chat", "/sessions", "/files", "/shared-assets", "/transcribe"].map(
          (p) => [p, backend]
        )
      ),
      "/share": { target: backend, bypass: (req) => req.url?.startsWith("/shared/") ? "/index.html" : undefined },
    },
  },
});
