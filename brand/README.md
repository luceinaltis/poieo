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

The landing uses a distant textured moon, thin moonlit cloud wisps and close
persimmon branches. Its night backdrop is generated separately without a moon,
stars or clouds, so the atmosphere never fixes their position. Both backdrops
are capped at 1280px wide, centered and faded at the edges; widening the window
does not enlarge branches into the headline. The light page has an airy blue-grey
sky and soft white sunlight. Its tree is a daylight edit of the night original,
preserving the branch layout and detailed leaves with muted green/ochre foliage
and orange fruit. Light always shows the sun; Dark
always shows the moon; Auto uses the visitor's local 06:00–18:00 day convention.
The body crosses left to right over each 12-hour arc, highest at noon/midnight.
Positions refresh each second, so real-time motion is intentionally very slow.
These are clock paths, not geographic sun/moon rise and set times.

The moon's illuminated shape follows an approximate synodic cycle of 29.530588
days from the 2025-01-29 12:36 UTC new moon. Four generated transparent images
depict crescent, quarter, gibbous and full phases with their own surface shading.
The nearest of eight key phases selects an image; waning phases mirror the
waxing art. This intentionally approximates both illumination and geography,
rather than clipping a photograph into a continuously changing silhouette.
The new-moon phase has no visible disc or halo. This northern-hemisphere convention
does not account for the observer's latitude, tilt, libration, or lunar-orbit
variations. Its label gives the approximate phase and illumination. The source
is [NASA's phase table](https://eclipse.gsfc.nasa.gov/phase/phase2001gmt.html).
Only the selected sun/moon image is requested, with the previous image hidden
until its replacement loads; no location or runtime service is used.

Thirty-two small decorative stars glow at different slow rhythms. They are
absent in Light. The same transparent cirrus catches white daylight or moonlight.
Clouds drift across the body, never over the
text. Reduced motion holds stars and clouds still and disables body transitions.
Hidden or cached pages pause; returning rereads the current clock and date.
A time jump, mode change or arc reset places the body directly, without a long
crossing. The scene stays behind text and controls and outside accessibility
navigation; the body retains its descriptive accessible label.

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
| `site/img/persimmon-wash.webp` | Original paper illustration retained for the share card |
| `site/img/sun.png`, `moon.png` | Earlier generated sky textures, retained as source references |
| `site/img/moon-full.png`, `moon-crescent.png`, `moon-quarter.png`, `moon-gibbous.png` | Generated transparent lunar key phases |
| `site/img/day-garden.png`, `sun-daylight.png` | Daylight relighting of the night persimmon composition and soft photographic sun |
| `site/img/night-garden.png`, `moonlit-wisp.png` | Generated night backdrop and transparent moving cirrus layer |
| `site/img/cloud-1.webp` … `cloud-3-light.webp` | Ink-wash cloud banks for dark ground and paper; regenerate with `brand/clouds.py` |
| `site/img/task.png`, `task-light.png`, `board.png` | Actual board with scripted, cost-free work |
| `site/social.html`, `site/img/social.png` | Source and 1280×640 share image |

The illustration's generation record is [wash-source.json](wash-source.json).
The night backdrop and wisp record is [night-source.json](night-source.json).
The active day and lunar images, complete prompts and hashes are in
[daylight-phases-source.json](daylight-phases-source.json).
The sun and moon's prompts, asset paths, and hashes are in [sky-source.json](sky-source.json);
the clouds have no prompt, and [clouds.py](clouds.py) is their record.
The Korean design rationale and selected reference are in
[docs/branding.md](../docs/branding.md). Retired concepts remain in git history.
