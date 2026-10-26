// A Storybook-like harness: the real client components (client/src) against a mocked API, for the
// screenshots in ../screenshots. Not part of the SDK build.
//   (once) mklink /J node_modules ..\..\client\node_modules      (or: ln -s ../../client/node_modules)
//   npx vite --config vite.config.mjs --port 5199
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: here,
  plugins: [react(), tailwindcss()],
  server: { fs: { allow: [fileURLToPath(new URL("../..", import.meta.url))] } },
});
