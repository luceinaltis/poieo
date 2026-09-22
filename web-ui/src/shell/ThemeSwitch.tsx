import { useLayoutEffect, useState } from "react"

import { MoonIcon, SunIcon } from "./icons"

type Theme = "light" | "dark"
const KEY = "poieo.theme"

function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === "light" || saved === "dark") return saved
  } catch { /* A private window can refuse storage. The switch still works. */ }
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark" : "light"
}

export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(readTheme)
  const next = theme === "light" ? "dark" : "light"

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content", theme === "light" ? "#f8f5ef" : "#100e0c",
    )
  }, [theme])

  return (
    <button
      className="shell-theme"
      type="button"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => {
        try { localStorage.setItem(KEY, next) } catch { /* Keep the in-memory choice. */ }
        setTheme(next)
      }}
    >
      {/* Drawn as the theme it would switch to, which is what the word said. */}
      {next === "light" ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}
