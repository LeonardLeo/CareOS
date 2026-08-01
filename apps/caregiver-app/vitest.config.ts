import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Kept separate from `vite.config.ts` rather than merged into it.
 *
 * vitest resolves its own copy of vite, so a single config that imports both `@vitejs/plugin-react`
 * (against the app's vite) and vitest's `defineConfig` type-checks two structurally identical
 * but nominally different `Plugin` types against each other and fails.
 *
 * Splitting them is not just a workaround: the unit tests here cover `src/lib`, which is
 * deliberately free of React and DOM imports so that a React Native shell could reuse it. A
 * test config with no React plugin and a node environment enforces that boundary — a component
 * import in one of these modules would fail to resolve here rather than pass unnoticed.
 */
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
