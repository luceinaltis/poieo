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
  //
  // `changeOrigin: false` is the default and is written out because the daemon
  // now depends on it: a write is refused when its `Origin` and its `Host`
  // disagree, and rewriting the Host to the target would make every write from
  // `npm run dev` look like another site. See `SameOrigin` in web/server.py.
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8484", changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
  },
})
