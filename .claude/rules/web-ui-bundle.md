---
paths:
  - "web-ui/src/**"
  - "web-ui/src/**/*"
---

# The checked-in bundle

You are editing the frontend source. **The built bundle is checked in, and rebuilding
it is part of the same PR:**

```bash
npm run build --workspace web-ui
```

Then commit `src/poieo/web/static/`. That folder is deliberately tracked — it is what
a fresh checkout serves — while `web-ui/dist/` and `node_modules/` are ignored.

Neither suite reads `src/poieo/web/static/`, so it drifts in silence. It once sat
four PRs behind `main`, and one of those four was a CSS fix, so a fresh checkout
served the bug `main` had already fixed — with both suites green over it the whole
time. A green run is not evidence that the bundle is current; only the rebuild is.
