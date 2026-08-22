import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  // The daemon serves this from its own package, so build straight into it:
  // `npm run build` is the whole publish step.
  build: {
    outDir: "../src/poieo/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  // Dev runs on 5173 while the daemon owns 8484; the proxy keeps the client
  // talking to same-origin /api either way.
  server: {
    proxy: { "/api": "http://127.0.0.1:8484" },
  },
  test: {
    environment: "jsdom",
  },
})
