"""Fill this example's memory. Run it once: `python examples/remembering/seed.py`.

A project's memory is a database, so it cannot be shipped as text the way the
cards and bindings are -- and a binary in a public repository is an artifact
nobody can read in a diff. So the example ships the *writing* instead, which is
more use anyway: what an entry is made of is right here, in the shape the
learning pass and the board both use.

The memory it builds is the one `docs/memory.md` describes -- two cards over one
memory, an entry scoped to each, one that reaches both, and one set aside.
"""

import sys
from pathlib import Path

try:  # an installed poieo, if there is one
    from poieo.memory import frontmatter, set_aside, write_entry, write_page
except ModuleNotFoundError:  # otherwise the checkout this file sits in
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from poieo.memory import frontmatter, set_aside, write_entry, write_page

# The project to fill: this folder, or one named on the command line, so a copy
# of the example somewhere else can be filled too.
HERE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent

PAGE = """\
<!--
This page is read whole by every run of every task in this project. Before
adding a line, ask: does it apply to every task? is violating it expensive?
would lookup fail to bring it up when needed? is it invisible in the code?
Four yeses earn the page; anything less belongs in a learned entry.
-->

- Never write outside the notebook folder.
- Dates in the notebook are ISO (2026-08-24); no other shapes.
- When an outside service refuses, note it in the notebook and move on --
  do not retry all night.
"""

ENTRIES = [
    (
        "batch-cap",
        "The feed api rejects batches over 50; split large loads before sending,\n"
        "and keep [[feeds-order]] in mind when they land.",
        {"scope": ["importer"], "anchors": ["notebook"]},
    ),
    (
        "feeds-order",
        # No word here is shared with the importer card. It arrives only by
        # being mentioned above, which is what the association step is for.
        "Alphabetical order keeps the digest stable; newest entries go last.",
        {"scope": ["importer"]},
    ),
    (
        "old-batch-cap",
        "The feed api rejects batches over 10.",
        {"scope": ["importer"]},
    ),
    (
        "rate-limits",
        "The outside feeds rate-limit hard around 02:00; when one refuses, note it\n"
        "in the notebook and come back after.",
        {"scope": ["global"]},
    ),
]


def main() -> None:
    write_page(HERE, PAGE)
    for slug, body, matter in ENTRIES:
        write_entry(HERE, slug, body, frontmatter(matter))
    # Nothing is deleted: an entry that stopped being true is superseded by the
    # one that replaced it, and stays where a person can still read it.
    set_aside(HERE, "old-batch-cap", "batch-cap")
    print(f"wrote {HERE / 'memory' / 'longterm.sqlite3'}")
    print("now try: poieo memory examples/remembering/tasks/importer.yaml")


if __name__ == "__main__":
    main()
