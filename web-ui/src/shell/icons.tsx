/**
 * The four small marks the bar uses, as inline SVG so they take the text's
 * colour and size and ship with the page: the board serves from a machine
 * that may have no internet, and an icon font fetched from the web would be
 * the one thing on it that fails there.
 */

const common = {
  "aria-hidden": true,
  focusable: false,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const

/** A speech bubble: a word with the model. */
export function ChatIcon() {
  return (
    <svg {...common}>
      <path d="M4 5h16v11H9l-5 4z" />
    </svg>
  )
}

/** A chip: the models this project can reach. */
export function ModelsIcon() {
  return (
    <svg {...common}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 6V3m6 3V3M9 21v-3m6 3v-3M6 9H3m18 0h-3M6 15H3m18 0h-3" />
    </svg>
  )
}

export function SunIcon() {
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
    </svg>
  )
}

export function MoonIcon() {
  return (
    <svg {...common}>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
    </svg>
  )
}
