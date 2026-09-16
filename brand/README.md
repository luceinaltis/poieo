# The poieo brand

**Less spend. Better work.**

Small and large models, working together.

Write a task. Choose its models. Let poieo keep it running.

poieo is a personal tool for recurring work. The aim is better accuracy at a
lower cost, with a result a person can inspect. The character is quiet, capable,
and clear. The product's words are **task, run, change**.

You choose the model for each step. Savings and accuracy depend on the models,
tasks, and checks. Do not imply automatic optimization, invent a savings
percentage, or present model size as proof of correctness. Cost appears when
the provider reports it or the configuration supplies prices.

## Identity

The approved direction is **wash and fruit**: warm paper, sparse ink, and a
single golden persimmon. The landing page places a short serif headline in
open space, with a pale branch entering from the edge. Documentation and the
installed board use clean surfaces so the work stays easy to read.

The persimmon tree has a curved trunk, three broad leaves, and one fruit with
a calyx. Its custom lowercase serif wordmark keeps all five letters of
**poieo** legible, with e and o joined. Keep these shapes. Do not use the tree
as a diagram or assign a model role to each branch.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="logo/poieo-reversed.svg">
  <img src="logo/poieo.svg" alt="poieo — persimmon tree and serif wordmark" width="540">
</picture>

## Logo masters

Every SVG is transparent and outlined, including the lettering. There are no
embedded raster images, fonts, or external resources. All variants use the
same paths traced from the approved large lockup.

| Combination | Light background | Dark background | One colour |
|---|---|---|---|
| Horizontal logo | [poieo.svg](logo/poieo.svg) | [poieo-reversed.svg](logo/poieo-reversed.svg) | [poieo-mono.svg](logo/poieo-mono.svg) |
| Symbol | [symbol.svg](logo/symbol.svg) | [symbol-reversed.svg](logo/symbol-reversed.svg) | [symbol-mono.svg](logo/symbol-mono.svg) |
| Wordmark | [wordmark.svg](logo/wordmark.svg) | [wordmark-reversed.svg](logo/wordmark-reversed.svg) | Same as the light version |

Use ink `#221e18` and gold `#d8a657` on a light background, ivory `#f0e7d9`
and the same gold on a dark one. Preserve the aspect ratio and clear space in
the viewBox. Use the symbol at 32 px or larger when its leaf detail must remain
clear; the favicon is an intentionally small use. The [logo preview](logo/preview.html)
shows combinations and small sizes.

The [approved raster](../docs/assets/branding/logo-persimmon-concept.png) remains
as the tracing source. [source.json](logo/source.json) records its hash, crop,
settings, and generation prompt. Edit the SVG masters; do not retrace the
smaller generated specimens.

## Colour

The website, docs, and board share these roles. Gold is used sparingly for the
fruit and primary actions. Green, red, and blue describe status. On light
surfaces, small gold text uses the darker ember colour for contrast.

| Token | Dark | Light | Purpose |
|---|---|---|---|
| Ground | `#100e0c` | `#f8f5ef` | Page |
| Panel | `#201c18` | `#ffffff` | Card or reading surface |
| Well | `#181513` | `#eee8df` | Graph and code background |
| Raised | `#2e2721` | `#e7dfd2` | Controls and selected navigation |
| Rule | `#332b23` | `#d6ccbd` | Quiet separation |
| Line | `#7d7164` | `#877966` | Outlines, graph wires |
| Text | `#f0e7d9` | `#221e18` | Primary text |
| Dim | `#a0958a` | `#635b50` | Supporting text |
| Ember | `#d8a657` | `#845617` | Focus, links, and review |
| Live | `#a9b665` | `#47602b` | Running work |
| Stop | `#e08a74` | `#9d4530` | Failure |
| Paused | `#7f9bb5` | `#456782` | Paused work |
| Paused rule | `#3b4652` | `#b8c7d2` | Paused surface edge |
| Paused text | `#9db4c9` | `#375771` | Paused label |
| Accent | `#d8a657` | `#d8a657` | Primary button fill |
| On accent | `#221e18` | `#221e18` | Primary button text |

The website and docs offer **Auto, Light, and Dark**. Auto is the default and
follows the visitor's local clock: light from 06:00 to 18:00, dark otherwise.
Existing Light/Dark choices still win. Save all three modes in `poieo.theme`
for that browser origin and reflect changes in other open tabs. If storage is
unavailable, the control still changes the current page. The installed board
keeps its separate Light/Dark control and system-preference fallback.

The landing's photographic sun belongs to a light page and its full moon to a
dark one. In Auto that is the local clock: sun from 06:00 to 18:00, moon
otherwise. A chosen Light or Dark keeps its own body at any hour. The arc keeps
the clock either way: the body rises on the left, crosses the high middle at
noon or midnight, and descends on the right, so a moon chosen at noon stands
where the sun was. This is a clock convention, not astronomical sunrise or
lunar-phase data. Keep the arc clear of text and controls, including on phones.
A soft ivory halo makes the moon luminous on dark ground. Use the generated
transparent assets; do not replace them with drawn icons. Only the current body
is loaded.

Three rendered clouds drift slowly across the sky in front of the sun or moon
and veil them as they pass. `brand/clouds.py` draws them procedurally: sun-lit
white with grey undersides for paper, moonlit grey for dark ground, each lit
from the upper left. Run it to regenerate the six transparent WebP files. The
layer is hidden from assistive technology and keeps to the sky band above the
headline, behind the header and the text. Do not
mirror or recolour a cloud in CSS; its light would come from the wrong side.

Update each minute while visible. Resume from the current time after sleep or
browser-history restoration. Reduced motion disables transitions and holds the
clouds still; switching bodies or returning after a time jump also places the
body immediately.

## Type and copy

Georgia gives the website and docs headings a restrained serif voice. Hanken
Grotesk carries prose and interface labels; DM Mono carries code and exact
data. The latter two are self-hosted with their OFL licences. The board keeps
its compact sans serif labels for scanning. The logo is drawn, not typeset.

The first screen has one headline, one descriptor, and **Get started**. Do
not add a paragraph repeating the promise. Supporting sections explain model
choices and show the actual board. Documentation prioritizes the article,
quiet navigation, and horizontally scrollable code. Five short guides each
open as a separate page: Get started, Models, Tasks, Changes, and Troubleshooting.
Keep the current page selected while reading; do not expand its headings into
the sidebar. Longer technical references stay in a folded section with their
own heading outline. On a phone, the menu folds under the current selection's
name. Keep body copy at least 16 px and routine labels at least 14 px.

Git projects run in a private copy with changes to accept or discard. Non-Git
folders are edited directly. Project memory is opt-in. Keep those limits
clear wherever the corresponding feature is explained.

## Published assets

| Asset | Purpose |
|---|---|
| `site/img/lockup.svg`, `lockup-light.svg` | Copies of the reversed and normal logo masters; website, README, installed board |
| `site/img/mark.svg`, `mark-light.svg` | Copies of the symbol masters |
| `site/img/wordmark.svg`, `wordmark-light.svg` | Copies of the lettering masters |
| `site/img/favicon.svg`, `apple-touch-icon.png` | Reversed persimmon symbol on dark ground |
| `site/img/persimmon-wash.webp` | Decorative landing illustration, generated from the approved page concept |
| `site/img/sun.png`, `moon.png` | ChatGPT Image-generated transparent sun and moon; original alpha and resolution preserved |
| `site/img/cloud-1.webp` … `cloud-3-light.webp` | Rendered clouds for dark ground and paper; regenerate with `brand/clouds.py` |
| `site/img/task.png`, `task-light.png`, `board.png` | Actual board with scripted, cost-free work |
| `site/social.html`, `site/img/social.png` | Source and 1280×640 share image |

The illustration's generation record is [wash-source.json](wash-source.json).
The sun and moon's prompts, asset paths, and hashes are in [sky-source.json](sky-source.json);
the clouds have no prompt, and [clouds.py](clouds.py) is their record.
The Korean design rationale and selected reference are in
[docs/branding.md](../docs/branding.md). Retired concepts remain in git history.
