#!/usr/bin/env python3
"""Compare the Japanese and English blog drafts structurally.

**Why this exists.** The bilingual rule is enforced in CI for `docs/ja` against `docs/en`, but the
blog drafts live under `.private/`, which is gitignored, so no gate sees them. In one session three
edits landed in Japanese and not in English: an unverifiable quotation was removed from one side
only, a set of four corrections to the second article reached one side only, and a claim about EC2
I/O limits was corrected on one side while the other kept saying the limit is bypassed. Each was
found by hand, twice by noticing a count that did not match.

So the counting is the check. It compares what a structural edit changes -- headings, figures,
tables, reference links -- and reports the pairs that disagree. **It cannot see a mistranslation or
a paragraph edited on one side with no structural effect**, which is why it prints what it compared
rather than only whether it passed.

Skips with a message when the drafts are absent, which is the normal state for a fresh clone: the
drafts are not in the repository. **A skip is not a pass.**

Run:  python3 tools/check_draft_parity.py
      python3 tools/check_draft_parity.py --selftest
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFTS = ROOT / ".private" / "blog-drafts"

# What a structural edit moves. Prose edits that change none of these are invisible here, which the
# module docstring says out loud rather than leaving the reader to assume coverage.
COUNTERS: dict[str, re.Pattern[str]] = {
    "h2": re.compile(r"^## ", re.M),
    "h3": re.compile(r"^### ", re.M),
    "figure": re.compile(r"^!\[", re.M),
    "table": re.compile(r"^\|---", re.M),
    "reference link": re.compile(r"^- \[", re.M),
    "fenced block": re.compile(r"^```", re.M),
}


def counts(body: str) -> dict[str, int]:
    return {name: len(pattern.findall(body)) for name, pattern in COUNTERS.items()}


def selftest() -> int:
    failures = 0
    same = "## a\n\n### b\n\n![x](y)\n\n|---|\n\n- [l](u)\n\n```\n"
    if counts(same) != counts(same):
        print("selftest: counting is not deterministic")
        failures += 1
    a = counts("## a\n")
    b = counts("## a\n\n## b\n")
    if a["h2"] != 1 or b["h2"] != 2:
        print(f"selftest: h2 counting is wrong ({a['h2']}, {b['h2']})")
        failures += 1
    if a == b:
        print("selftest: a differing pair compared equal")
        failures += 1
    # A heading inside a fence is still counted; that is accepted, and stated so a reader does not
    # read a false negative as coverage.
    if counts("```\n## not a heading\n```\n")["h2"] != 1:
        print("selftest: fenced-heading behaviour changed without the docstring changing")
        failures += 1
    print(
        "draft-parity selftest: OK"
        if not failures
        else f"draft-parity selftest: {failures} failure(s)"
    )
    return 1 if failures else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    ja_dir, en_dir = DRAFTS / "ja", DRAFTS / "en"
    if not ja_dir.is_dir() or not en_dir.is_dir():
        print("draft-parity: no .private/blog-drafts/{ja,en}; skipped. **A skip is not a pass.**")
        return 0

    pairs = []
    for ja in sorted(ja_dir.glob("blog-*.md")):
        if ja.name.endswith((".hatena.md", ".post-meta.md")):
            continue
        en = en_dir / ja.name
        if en.exists():
            pairs.append((ja, en))

    if not pairs:
        print("draft-parity: no JA/EN pairs found; skipped. **A skip is not a pass.**")
        return 0

    problems = 0
    for ja, en in pairs:
        cja, cen = counts(ja.read_text(encoding="utf-8")), counts(en.read_text(encoding="utf-8"))
        diffs = {k: (cja[k], cen[k]) for k in COUNTERS if cja[k] != cen[k]}
        shown = ", ".join(f"{k} {cja[k]}" for k in COUNTERS)
        if diffs:
            problems += 1
            print(f"draft-parity: {ja.name}")
            for key, (left, right) in diffs.items():
                print(f"    {key}: JA {left} / EN {right}")
        else:
            print(f"draft-parity: {ja.name} matches ({shown})")

    if problems:
        print(
            f"draft-parity: {problems} pair(s) disagree. A structural edit reached one language "
            "only. **Equal counts do not prove the prose matches.**"
        )
        return 1
    print(f"draft-parity: {len(pairs)} pair(s) match on {len(COUNTERS)} counters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
