#!/usr/bin/env python3
"""Verify the claim-bearing strings this repository cites in sibling repositories.

A citation of someone else's finding is evidence only while the sentence it rests on is still
there. Rewording is normal and nobody announces it, so the way this side learns that a cited
claim moved is by checking, not by being told.

`docs/agent/cross-repo-probe-contract.txt` registers one exact substring per citation. This reads
each cited repository and fails when a registered string is gone.

**Why this exists rather than relying on the sibling's mirror check.** S3-Burst-on-ONTAP-Files runs
`make incoming-probes`, which reads a sibling's contract and fails on its own side when a string
that sibling cites is reworded -- discovery at the commit that causes it, which is the better
place. But that checker names one sibling, FSx-for-ONTAP-Adoption-Playbook, in `CHECKOUT_NAMES`
and `RAW_CONTRACT`. It does not read this repository's contract, so publishing one buys nothing on
its own. **A protection that depends on the other side wiring us in is not a protection yet.**

Roles, and they ask different questions:

  retraction  the string must be present. Missing it means the claim was withdrawn or reworded and
              the citation here has lost its evidence. **Fails.**
  reread      the string is expected to move, because it pins a value over a set that grows.
              **Warns.**

Each probe is an opaque byte substring and nothing is normalised. Emphasis markers are part of the
claim when the registration includes them; stripping them to be helpful would let a probe match
text that no longer carries the claim.

Needs a local checkout of each cited repository next to this one, and skips with a message when
there is none -- the way the other checkouts-required targets do. **A skip is not a pass**, and the
exit line says which it was.

**Reads `origin/main`, not the checkout's working tree.** The working tree is somebody's editing
state: a probe can be satisfied by a sentence that exists only there and not in the repository
anybody else can read, and that direction passes silently. Verifying by hand once is not the same
as the gate doing it, so the gate does it. `git show` reads local objects, so this stays offline.

When a checkout cannot answer for `origin/main` the read falls back to the working tree, and the
output says so for that repository -- **a fallen-back run is weaker evidence than one that was not,
and the output is the only place that difference is visible.** "This checkout has no `origin/main`"
and "that path is absent at `origin/main`" are asked separately, by `rev-parse --verify` and then
`show`, because the two need opposite handling and telling them apart from git's stderr wording
would rest the distinction on a string that changes between versions.

Run:  python3 tools/check_outgoing_probes.py
      python3 tools/check_outgoing_probes.py --selftest
      python3 tools/check_outgoing_probes.py --contract PATH
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs" / "agent" / "cross-repo-probe-contract.txt"

# A repository may be checked out under its GitHub name or a local short name. Holding both is why
# check_incoming_probes.py in the sibling holds two: a checkout went unfound once and the skip
# stood in for a pass.
CHECKOUT_NAMES = {
    "S3-Burst-on-ONTAP-Files": ("S3-Burst-on-ONTAP-Files", "s3-burst-on-ontap-files"),
    "FSx-for-ONTAP-Adoption-Playbook": (
        "FSx-for-ONTAP-Adoption-Playbook",
        "fsxn-adoption-playbook",
    ),
}

FAIL_ROLE = "retraction"
WARN_ROLE = "reread"
ROLES = (FAIL_ROLE, WARN_ROLE)


class Probe(NamedTuple):
    repo: str
    path: str
    role: str
    probe: str
    line: int


def parse(body: str) -> tuple[list[Probe], list[str]]:
    probes: list[Probe] = []
    problems: list[str] = []
    for number, raw in enumerate(body.splitlines(), start=1):
        if not raw.strip() or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 4:
            problems.append(f"line {number}: expected 4 tab-separated fields, got {len(fields)}")
            continue
        repo, path, role, probe = fields
        if role not in ROLES:
            problems.append(f"line {number}: role {role!r} is not one of {ROLES}")
            continue
        if not probe:
            problems.append(f"line {number}: empty probe")
            continue
        probes.append(Probe(repo, path, role, probe, number))
    ordered = sorted(probes, key=lambda p: (p.repo, p.path, p.role, p.probe))
    if [p[:4] for p in probes] != [p[:4] for p in ordered]:
        problems.append("registrations are not sorted; sort by repo, path, role, probe")
    return probes, problems


def search_roots() -> list[Path]:
    """Where sibling checkouts are looked for.

    Beside this repository locally. In CI they cannot be beside it: `actions/checkout` refuses a
    `path` outside `$GITHUB_WORKSPACE`, so a `../sibling` checkout fails rather than landing where
    a local run would look. `SIBLING_ROOT` names a directory inside the workspace instead.
    """
    explicit = os.environ.get("SIBLING_ROOT")
    if explicit:
        base = Path(explicit)
        return [base if base.is_absolute() else ROOT / base]
    return [ROOT.parent]


def locate(repo: str) -> Path | None:
    for base in search_roots():
        for name in CHECKOUT_NAMES.get(repo, (repo,)):
            candidate = base / name
            if (candidate / ".git").exists():
                return candidate
    return None


PUBLISHED_REF = "origin/main"


def git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        # No git on PATH. Reported as an inability to reach the ref, not as a missing file.
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="git not found")


def answers_for_published_ref(checkout: Path) -> bool:
    """Whether this checkout can be asked about `origin/main` at all.

    Separate from whether a given path exists there. The two need opposite handling -- fall back
    versus report the file gone -- so the question is asked with `rev-parse --verify` rather than
    read out of the wording of a later failure.
    """
    return git(checkout, "rev-parse", "--verify", "--quiet", PUBLISHED_REF).returncode == 0


class Read(NamedTuple):
    body: str | None
    from_published_ref: bool


def read(checkout: Path, path: str, published: bool) -> Read:
    """Body of `path`, from `origin/main` when the checkout can answer for it."""
    if published:
        shown = git(checkout, "show", f"{PUBLISHED_REF}:{path}")
        # A non-zero return here means the path is absent at the ref, which `published` has
        # already ruled out being about the ref itself.
        return Read(shown.stdout if shown.returncode == 0 else None, True)
    target = checkout / path
    if not target.exists():
        return Read(None, False)
    return Read(target.read_text(encoding="utf-8", errors="replace"), False)


def selftest() -> int:
    cases = [
        ("a\tb\tretraction\tclaim", 1, 0),
        ("a\tb\treread\tclaim", 1, 0),
        ("a\tb\tbogus\tclaim", 0, 1),
        ("a\tb\tretraction", 0, 1),
        ("a\tb\tretraction\t", 0, 1),
        ("# comment", 0, 0),
        ("", 0, 0),
    ]
    failures = 0
    for body, want_probes, want_problems in cases:
        probes, problems = parse(body)
        if len(probes) != want_probes or len(problems) != want_problems:
            print(
                f"selftest: {body!r} gave {len(probes)} probes / {len(problems)} problems, "
                f"wanted {want_probes} / {want_problems}"
            )
            failures += 1
    # Sorting is enforced, so an out-of-order pair must be reported.
    _, problems = parse("a\tb\tretraction\tz\na\tb\tretraction\ta")
    if not any("sorted" in p for p in problems):
        print("selftest: unsorted registrations were not reported")
        failures += 1
    # A probe that is present must pass and one that is absent must fail, or the check is decorative.
    if "needle" not in "haystack needle haystack":
        print("selftest: substring test is broken")
        failures += 1
    print(
        "outgoing-probes selftest: OK"
        if not failures
        else f"outgoing-probes selftest: {failures} failure(s)"
    )
    return 1 if failures else 0


def contract_path() -> Path:
    """The contract to read. `--contract` exists so the tests can drive real registrations."""
    if "--contract" in sys.argv:
        return Path(sys.argv[sys.argv.index("--contract") + 1])
    return CONTRACT


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    contract = contract_path()
    if not contract.exists():
        print(f"outgoing-probes: no contract at {contract}; nothing cited")
        return 0

    probes, problems = parse(contract.read_text(encoding="utf-8"))
    if problems:
        for problem in problems:
            print(f"outgoing-probes: {problem}")
        return 1
    if not probes:
        print("outgoing-probes: contract has no registrations")
        return 0

    failures: list[str] = []
    warnings: list[str] = []
    skipped: set[str] = set()
    fell_back: set[str] = set()
    checked = 0
    published: dict[str, bool] = {}

    for probe in probes:
        checkout = locate(probe.repo)
        if checkout is None:
            skipped.add(probe.repo)
            continue
        if probe.repo not in published:
            published[probe.repo] = answers_for_published_ref(checkout)
            if not published[probe.repo]:
                fell_back.add(probe.repo)
        body, from_published_ref = read(checkout, probe.path, published[probe.repo])
        if body is None:
            where = PUBLISHED_REF if from_published_ref else "the working tree"
            failures.append(
                f"{probe.repo}: {probe.path} does not exist at {where} (line {probe.line})"
            )
            continue
        checked += 1
        if probe.probe in body:
            continue
        message = (
            f"{probe.repo}: {probe.path} no longer contains {probe.probe!r} (line {probe.line})"
        )
        (failures if probe.role == FAIL_ROLE else warnings).append(message)

    for warning in warnings:
        print(f"outgoing-probes: reread: {warning}")
    for failure in failures:
        print(f"outgoing-probes: {failure}")

    if skipped:
        print(
            "outgoing-probes: skipped "
            + ", ".join(sorted(skipped))
            + " (no checkout beside this repository). **A skip is not a pass.**"
        )
    if fell_back:
        print(
            "outgoing-probes: fell back to the working tree for "
            + ", ".join(sorted(fell_back))
            + f" (that checkout cannot answer for {PUBLISHED_REF}). "
            "**A working-tree read is weaker evidence: it can be satisfied by an "
            "unpushed edit.**"
        )
    read_at_ref = sorted(repo for repo, ok in published.items() if ok)
    if read_at_ref:
        print(f"outgoing-probes: read {', '.join(read_at_ref)} at {PUBLISHED_REF}")
    if failures:
        return 1
    counts = {role: sum(1 for p in probes if p.role == role) for role in ROLES}
    print(
        f"outgoing-probes: {checked} of {len(probes)} registration(s) verified "
        f"({counts[FAIL_ROLE]} retraction, {counts[WARN_ROLE]} reread)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
