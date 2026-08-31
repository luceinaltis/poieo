# The poieo brand

**Your models, at work.** The brand has one picture and one promise. The
**tree** shows work that keeps growing after the task is written: crooked
branches are work in motion, the buds are continuing tasks, and the single
amber fruit is a change ready for review. The voice stays plain and user-side:
the reader chooses the models and schedule, then decides what reaches their
files.

The product should feel like a quiet working team without pretending the
models are people. No faces, names, avatars, or employee cards enter the
interface. Its vocabulary remains **task, run, change**.

The look began with a photographed kinetic sculpture (a sphere sprouting
crooked ball-tipped stalks) and was distilled through tree studies into the
current mark.

## The mark system

Everything below is **traced from an approved generated image, never redrawn
by hand** — a hand redraw drifted once (#258) and the rule exists because of
it. To change a mark: generate, get it approved, trace, replace.

| asset | what it is |
|---|---|
| `site/img/mark.svg` | the mark — a small crooked tree, five buds, one amber |
| `site/img/favicon.svg` | the same tree on its own dark plate, for grounds we do not control |
| `site/img/wordmark.svg` | `poieo` in custom monoline lettering; the e flows into the final o as a small infinity |
| `site/img/lockup.svg` / `lockup-light.svg` | mark + wordmark, for dark and light grounds |
| `site/img/mark-light.svg` / `wordmark-light.svg` | the same traced paths in ink, for the site's light theme |
| `site/img/social.png` | the 1280×640 share card; its source page is `site/social.html` |
| `mark-source.jpg` (here) | the generation the mark's SVG is traced from |
| `wordmark-source.png` (here) | the generation the wordmark's SVG is traced from |

## Colour

Inherited from the product's own board (`web-ui/src`), so the brand and the
running software are one thing:

| token | hex | job |
|---|---|---|
| Ground | `#100e0c` | the warm near-black everything sits on |
| Panel | `#201c18` | a task card on the ground |
| Well | `#181513` | a recessed graph or field inside a card |
| Raised | `#2e2721` | buttons and steps |
| Rule | `#332b23` | hairlines and quiet borders |
| Line | `#7d7164` | wires, arrowheads, and stronger outlines |
| Parchment | `#f0e7d9` | shapes and body text on dark |
| Dim | `#a0958a` | supporting copy that remains readable |
| Ember | `#d8a657` | the one ripe bud; every accent |
| Live | `#a9b665` | the product's own "running right now" — the board owns this word, not the mark |
| Stop | `#e08a74` | failure and direct-file risk |
| Ink | `#221e18` | what parchment becomes on light grounds |

## Type

- **Wordmark**: the traced custom lettering only — never set the name in a font.
- **Sentences**: Hanken Grotesk. **Labels, figures, code**: DM Mono. Both
  OFL, and the site ships them itself (`site/fonts/`, latin subsets, no
  external request) — leaning on visitors' system stacks made the typography
  a lottery, and one custom browser default changed the page's whole voice.

## Rules

1. **Crooked stays crooked.** Do not straighten the branches, and do not
   redraw them by hand — trace.
2. **One amber, never more.** The amber bud is the ripe one — the fruit
   worth the reader's attention — not a status lamp: on the board, "running"
   is Live green. Two ambers make it decoration.
3. **Flat vector.** No gradients, no texture, no shadows.
4. **On light grounds**, parchment becomes ink; the amber stays.
5. **No forge imagery.** The blacksmith-workshop register (smiths, anvils,
   fires) is retired from every brand surface — README, site, cards,
   screenshots. The atelier skin that carried it has since been removed from
   the product as well; nothing renders a forge anywhere now.

## Voice

The active copy hierarchy is fixed:

- **Headline:** Your models, at work.
- **Descriptor:** An autonomous task board for the models you choose.
- **Explanation:** Write a task once. poieo keeps it running on the models you choose—on your machine, on your schedule—and brings every change back for your approval.

Explain the product in the order a person experiences it: **Write the task →
Let it run → Review the change.** Night and morning may illustrate a use case,
but they are not the brand promise.

## Registers — reference images

Three generations kept here set the range of the voice. Keep their qualities,
not their exact pixels:

| file | register |
|---|---|
| `reference-crooked-tree.jpg` | **rich** — the full wilful tree; hero and card art (`site/img/tree.jpg` is a copy) |
| `reference-windswept-tree.png` | **dramatic** — motion, one fruit about to let go; note it arrived on a light ground, which reads as the light-theme voice (`site/img/tree-light.jpg` is a copy) |
| `reference-ikebana-branch.png` | **minimal** — one pruned branch, editorial air; where small or quiet surfaces should head |
