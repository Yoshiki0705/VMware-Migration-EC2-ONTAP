"""The gate set must be defined once, not described in two places.

Measured in this repository: the Makefile said `diagram-fonts` and `diagram-flow`
were placed in `drift` so that "CI runs them always". `ci.yml` never invoked
`drift`; it invoked `context-budget` on its own. **Three diagram gates therefore
never ran in CI**, and the comment asserting that they did stayed true-looking
because nothing compared the two files.

`make gates` is now the single definition, and this test fails when `ci.yml`
stops matching it. The list may change freely — but it cannot change in one file
only.

The test also proves its own parsing against deliberately broken input, so a
parser that stopped matching fails here rather than reporting two empty sets as
equal.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Targets a runner invokes that are setup rather than gates.
SETUP_TARGETS = {"install", "tools"}

# Declared in ci.yml as its own job, because it is a system binary rather than a
# pinned Python package, so it is not part of the portable `gates` set.
SEPARATE_JOB_TARGETS = {"shellcheck"}

GATES_RE = re.compile(r"^gates:\s*(?P<prereqs>[^#]*)", re.MULTILINE)
# `- ` is optional: a step may carry a `name:` and put `run:` on its own line, or
# be written as a bare `- run:`. Requiring one shape would make the parser quietly
# narrower than the file it reads, which is how a comparison returns two empty
# sets and calls them equal.
RUN_MAKE_RE = re.compile(
    r"^\s*(?:-\s+)?run:\s*make\s+(?P<target>[a-z][a-z0-9-]*)\s*$", re.MULTILINE
)


def gates_prerequisites(makefile_text: str) -> list[str]:
    match = GATES_RE.search(makefile_text)
    assert match, "Makefile has no `gates:` target. The single definition is gone."
    return match.group("prereqs").split()


def ci_make_targets(workflow_text: str) -> list[str]:
    found = [m.group("target") for m in RUN_MAKE_RE.finditer(workflow_text)]
    return [t for t in found if t not in SETUP_TARGETS | SEPARATE_JOB_TARGETS]


def test_ci_runs_exactly_the_gates_target() -> None:
    gates = gates_prerequisites(MAKEFILE.read_text(encoding="utf-8"))
    invoked = ci_make_targets(CI_WORKFLOW.read_text(encoding="utf-8"))

    only_in_makefile = sorted(set(gates) - set(invoked))
    only_in_ci = sorted(set(invoked) - set(gates))

    assert not only_in_makefile, (
        f"`make gates` lists {only_in_makefile}, which ci.yml never runs. "
        "A gate believed to run in CI that does not is the failure this test exists for."
    )
    assert not only_in_ci, (
        f"ci.yml runs {only_in_ci}, which is not in `make gates`. "
        "Add it to the Makefile so a local run covers the same set."
    )


def test_no_gate_is_listed_twice_in_ci() -> None:
    invoked = ci_make_targets(CI_WORKFLOW.read_text(encoding="utf-8"))
    duplicates = sorted({t for t in invoked if invoked.count(t) > 1})
    assert not duplicates, f"ci.yml runs these twice: {duplicates}"


# ---------------------------------------------------------------- parser proof


def test_parser_detects_a_missing_target() -> None:
    """A gate present in the Makefile and absent from CI must be reported."""
    gates = gates_prerequisites("gates: lint test diagram-flow ## doc\n")
    invoked = ci_make_targets("      - run: make lint\n      - run: make test\n")
    assert sorted(set(gates) - set(invoked)) == ["diagram-flow"]


def test_parser_ignores_setup_and_separate_jobs() -> None:
    workflow = (
        "      - run: make install\n"
        "      - run: make tools\n"
        "      - run: make shellcheck\n"
        "      - run: make lint\n"
    )
    assert ci_make_targets(workflow) == ["lint"]


def test_parser_stops_at_the_makefile_comment() -> None:
    """`## help text` must not be read as a prerequisite."""
    assert gates_prerequisites("gates: lint test ## どこでも走る検査\n") == ["lint", "test"]
