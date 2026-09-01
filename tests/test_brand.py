"""The public promise and the product share one brand contract.

These surfaces are maintained by hand and otherwise drift independently: the
landing page, its share card, the README, the brand guide, and the board's CSS.
The checks here hold only the few words and colours that must remain identical.

Design: brand/README.md
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADLINE = "Your models, at work."
DESCRIPTOR = "An autonomous task board for the models you choose."
EXPLANATION = (
    "Write a task once. poieo keeps it running on the models you choose—on your machine, "
    "on your schedule—and brings every change back for your approval."
)
ACTIVE_SURFACES = [ROOT / "README.md", ROOT / "brand" / "README.md", ROOT / "site" / "index.html"]
CORE_TOKENS = {"ground", "panel", "well", "raised", "rule", "line", "text", "dim", "ember", "live", "stop"}
DARK_BRAND_ASSETS = [ROOT / "site" / "img" / name for name in ("favicon.svg", "lockup.svg", "mark.svg", "wordmark.svg")]


@pytest.mark.parametrize("path", ACTIVE_SURFACES, ids=lambda path: str(path.relative_to(ROOT)))
def test_active_brand_surfaces_use_one_headline(path: Path):
    text = path.read_text(encoding="utf-8")
    assert HEADLINE in text
    assert "conduct" not in text.lower()


def test_landing_tells_the_whole_story_in_order():
    source = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    page = source.split("<main>", 1)[1]
    promises = [HEADLINE, DESCRIPTOR, EXPLANATION, "Write the task", "Let it run", "Review the change"]
    positions = [page.index(promise) for promise in promises]
    assert positions == sorted(positions)


def test_readme_carries_the_descriptor_and_explanation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert DESCRIPTOR in readme
    assert EXPLANATION in readme


def test_share_card_carries_the_headline():
    source = (ROOT / "site" / "social.html").read_text(encoding="utf-8")
    assert HEADLINE in source


def _dark_tokens(path: Path) -> dict[str, str]:
    css = path.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert root
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", root.group(1)))


def test_site_and_product_share_the_core_dark_palette():
    product = _dark_tokens(ROOT / "web-ui" / "src" / "index.css")
    site = _dark_tokens(ROOT / "site" / "style.css")
    assert CORE_TOKENS <= product.keys()
    assert CORE_TOKENS <= site.keys()
    assert {name: site[name] for name in CORE_TOKENS} == {name: product[name] for name in CORE_TOKENS}


@pytest.mark.parametrize("path", DARK_BRAND_ASSETS, ids=lambda path: path.name)
def test_dark_brand_assets_use_the_product_text_colour(path: Path):
    product = _dark_tokens(ROOT / "web-ui" / "src" / "index.css")
    assert product["text"].lower() in path.read_text(encoding="utf-8").lower()


def test_favicon_uses_the_product_ground_colour():
    product = _dark_tokens(ROOT / "web-ui" / "src" / "index.css")
    favicon = (ROOT / "site" / "img" / "favicon.svg").read_text(encoding="utf-8")
    assert product["ground"].lower() in favicon.lower()


def test_landing_headline_can_wrap_on_a_narrow_screen():
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    base_rule = re.search(r"\.hero h1\s*\{([^}]*)\}", css, re.S)
    assert base_rule
    assert "white-space: nowrap" not in base_rule.group(1)


def test_landing_keeps_the_brand_tree_out_of_the_product_demo():
    source = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    hero = re.search(r'<section class="hero".*?</section>', source, re.S)
    demo = re.search(r'<section class="cycle".*?</section>', source, re.S)
    assert hero
    assert demo
    assert "hero-art" in hero.group(0)
    assert "data-demo-panel" not in hero.group(0)
    assert "hero-art" not in demo.group(0)
    assert "data-demo-panel" in demo.group(0)


def test_landing_demo_has_three_scroll_examples_and_arrow_controls():
    source = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r"data-demo-step=", source)) == 3
    assert len(re.findall(r"data-demo-panel=", source)) == 3
    assert "data-demo-prev" in source
    assert "data-demo-next" in source
    assert 'aria-live="polite"' in source
    assert '<script src="landing.js" defer></script>' in source


def test_landing_demo_has_motion_and_small_screen_fallbacks():
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    script = (ROOT / "site" / "landing.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert "prefers-reduced-motion: reduce" in script
    assert "IntersectionObserver" in script
    assert "scrollIntoView" in script
    assert ".demo-mobile-shot" in css


def test_running_tasks_use_live_green_not_the_review_accent():
    css = (ROOT / "web-ui" / "src" / "skins" / "basic" / "basic.css").read_text(encoding="utf-8")
    running = re.findall(r'\.basic-task\[data-status="running"\][^{]*\{([^}]+)\}', css)
    paint = [rule for rule in running if "background:" in rule or "border-color:" in rule]
    assert paint
    assert all("var(--live)" in rule and "var(--ember)" not in rule for rule in paint)


def test_product_components_use_the_shared_palette_tokens():
    styles = [path for path in (ROOT / "web-ui" / "src").rglob("*.css") if path.name != "index.css"]
    hardcoded = {
        str(path.relative_to(ROOT)): re.findall(r"#[0-9a-fA-F]{3,8}", path.read_text(encoding="utf-8"))
        for path in styles
    }
    assert not {path: colours for path, colours in hardcoded.items() if colours}


def test_memory_set_aside_control_uses_the_memory_accent():
    css = (ROOT / "web-ui" / "src" / "memory" / "memory.css").read_text(encoding="utf-8")
    assert "accent-color: var(--memory-highlight)" in css
    assert "--memory-violet" not in css


def test_memory_copy_has_a_readable_compact_floor():
    css = (ROOT / "web-ui" / "src" / "memory" / "memory.css").read_text(encoding="utf-8")
    rem_sizes = [float(size) for size in re.findall(r"font-size:\s*([\d.]+)rem", css)]
    assert rem_sizes
    assert min(rem_sizes) >= 0.875


@pytest.mark.parametrize(
    "selector",
    [".shell-project", ".shell-project-pick", ".shell-status", ".shell-pick", ".shell-rail button"],
)
def test_primary_shell_labels_stay_at_least_fourteen_pixels(selector: str):
    css = (ROOT / "web-ui" / "src" / "app.css").read_text(encoding="utf-8")
    rule = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.S)
    assert rule
    size = re.search(r"font-size:\s*([\d.]+)rem", rule.group(1))
    assert size
    assert float(size.group(1)) >= 0.875


def test_phone_navigation_keeps_its_larger_labels_on_one_line():
    css = (ROOT / "web-ui" / "src" / "app.css").read_text(encoding="utf-8")
    buttons = re.search(r"\.shell-rail button\s*\{([^}]*)\}", css, re.S)
    assert buttons
    assert "white-space: nowrap" in buttons.group(1)

    phone = css.split("@media (max-width: 720px)", 1)[1]
    rail = re.search(r"\.shell-rail\s*\{([^}]*)\}", phone, re.S)
    assert rail
    assert "gap: 1px" in rail.group(1)
    assert "padding: 0 4px" in rail.group(1)

    phone_buttons = re.search(r"\.shell-rail button\s*\{([^}]*)\}", phone, re.S)
    assert phone_buttons
    assert "padding-inline: 4px" in phone_buttons.group(1)
