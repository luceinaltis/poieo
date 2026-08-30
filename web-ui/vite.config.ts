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
  // `changeOrigin: false` is load-bearing, and is why this is spelled out
  // rather than left as the `"/api": "http://..."` shorthand: **the shorthand
  // expands to `changeOrigin: true`**, which rewrites the Host to the target
  // while the browser's Origin stays `http://localhost:5173`. The daemon
  // refuses a write whose Origin and Host disagree, so every pause, accept and
  // model change from `npm run dev` would 403. See `SameOrigin` in
  // web/server.py; do not fold this back into the shorthand.
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8484", changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
  },
})
