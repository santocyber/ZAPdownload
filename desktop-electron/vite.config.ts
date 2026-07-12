import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  root: "src/renderer",
  base: "./",
  build: {
    outDir: "../../dist/renderer",
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "src/renderer/index.html"),
    },
  },
});
