# The poieo brand

**The work grows like a tree; you conduct it.** The brand runs on two
metaphors with separate jobs and no third. The **tree** is the picture:
something alive and a little wilful, branches growing where they decide to,
a bud on every twig, one amber where something ripened. **Conducting** is the
voice: the reader stops doing tasks and starts directing them. Every visual
decision answers to the tree; every sentence answers to the conductor.

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
| `site/img/social.png` | the 1280×640 share card; its source page is `site/social.html` |
| `mark-source.jpg` (here) | the generation the mark's SVG is traced from |
| `wordmark-source.png` (here) | the generation the wordmark's SVG is traced from |

## Colour

Inherited from the product's own board (`web-ui/src`), so the brand and the
running software are one thing:

| token | hex | job |
|---|---|---|
| Ground | `#14120f` | the warm near-black everything sits on |
| Parchment | `#e8e2d8` | shapes and body text on dark |
| Ember | `#d8a657` | the one ripe bud; every accent |
| Live | `#a9b665` | the product's own "running right now" — the board owns this word, not the mark |
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

## Registers — reference images

Three generations kept here set the range of the voice. Keep their qualities,
not their exact pixels:

| file | register |
|---|---|
| `reference-crooked-tree.jpg` | **rich** — the full wilful tree; hero and card art (`site/img/tree.jpg` is a copy) |
| `reference-windswept-tree.png` | **dramatic** — motion, one fruit about to let go; note it arrived on a light ground, which reads as the light-theme voice |
| `reference-ikebana-branch.png` | **minimal** — one pruned branch, editorial air; where small or quiet surfaces should head |
