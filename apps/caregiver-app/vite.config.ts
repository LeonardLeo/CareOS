import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { precacheManifest } from "./build/precache-plugin";

export default defineConfig({
  plugins: [react(), precacheManifest()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    // Named without a content hash so the service worker's precache list is stable across
    // builds. A hashed filename would need the list regenerated on every build, which is the
    // usual reason a hand-written service worker starts serving a stale shell forever.
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
