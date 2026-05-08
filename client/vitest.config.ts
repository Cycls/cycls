/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Standalone vitest config — keeps the FE's vite.config.ts focused on
// the browser bundle (proxies, build outDir for hatch artifacts) while
// tests get a jsdom environment with React available.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
