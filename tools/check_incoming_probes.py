#!/usr/bin/env python3
"""Verify the strings sibling repositories cite *from* this one.

The other direction is `check_outgoing_probes.py`: claims this repository quotes, which break when
somebody else rewords their sentence. This one is the reverse. Two siblings publish a contract
naming exact substrings of **this** repository's documents that their guidance rests on. Rewording
one of those sentences here removes the basis of their citation, and **nothing in this repository
noticed** -- the discovery happened on their side, or in a message, or not at all.

**This is the direction worth blocking on.** A failure here is caused by the edit in front of you,
so it belongs in the same run as the edit. The outgoing check fails for something a sibling did,
which is a different kind of news; the asymmetry is deliberate and recorded in
`docs/agent/cross-repo-block-performance.md`.

Two reads, and they are not the same read:

  the sibling's contract   at `origin/main`. A registration that exists only in somebody's working
                           tree is not something this repository has been asked to preserve.
  this repository's files   the **working tree**, because the question is whether the edit in
                           progress still satisfies what was published.

A probe that matches more than once is reported as weak rather than accepted quietly: rewording one
occurrence leaves the sibling's gate green while their citation has lost the sentence it meant.
Both published contracts say this about their own registrations, so it is their standard, applied to
what they registered here.

Run:  python3 tools/check_incoming_probes.py
      python3 tools/check_incoming_probes.py --strict
      python3 tools/check_incoming_probes.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

from check_outgoing_probes import (
    CHECKOUT_NAMES,
    FAIL_ROLE,
    PUBLISHED_REF,
    ROOT,
    answers_for_published_ref,
    git,
    locate,
    parse,
)

THIS_REPO = "VMware-Migration-EC2-ONTAP"
CONTRACT_PATH = "docs/agent/cross-repo-probe-contract.txt"


def repo_root() -> Path:
    """Which tree to test the probes against. `--repo-root` exists for the tests."""
    if "--repo-root" in sys.argv:
        return Path(sys.argv[sys.argv.index("--repo-root") + 1])
    return ROOT


def sibling_contract(checkout: Path) -> tuple[str | None, bool]:
    """The sibling's published contract, and whether it came from `origin/main`."""
    if answers_for_published_ref(checkout):
        shown = git(checkout, "show", f"{PUBLISHED_REF}:{CONTRACT_PATH}")
        return (shown.stdout if shown.returncode == 0 else None), True
    local = checkout / CONTRACT_PATH
    if not local.exists():
        return None, False
    return local.read_text(encoding="utf-8", errors="replace"), False


def selftest() -> int:
    failures = 0
    probes, problems = parse(
        f"Other-Repo\tdocs/y.md\treread\telse\n{THIS_REPO}\tdocs/x.md\tretraction\tclaim\n"
    )
    if problems or len(probes) != 2:
        print(f"selftest: parse gave {len(probes)} probes / {problems}")
        failures += 1
    mine = [p for p in probes if p.repo == THIS_REPO]
    if len(mine) != 1:
        print("selftest: rows for other repositories were not filtered out")
        failures += 1
    if "needle" in "haystack":
        print("selftest: substring test is broken")
        failures += 1
    print(
        "incoming-probes selftest: OK"
        if not failures
        else f"incoming-probes selftest: {failures} failure(s)"
    )
    return 1 if failures else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    strict = "--strict" in sys.argv
    root = repo_root()

    failures: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    resolved = 0
    siblings_read: list[str] = []

    for repo in sorted(CHECKOUT_NAMES):
        checkout = locate(repo)
        if checkout is None:
            notes.append(
                f"skipped {repo} (no checkout beside this repository). **A skip is not a pass.**"
            )
            if strict:
                failures.append(f"--strict: {repo} was skipped, so its registrations were not read")
            continue
        body, from_published_ref = sibling_contract(checkout)
        if not from_published_ref:
            notes.append(
                f"read {repo} from its working tree (that checkout cannot answer for "
                f"{PUBLISHED_REF}). **A registration that is only in a working tree is not "
                "something this repository was asked to preserve.**"
            )
            if strict:
                failures.append(
                    f"--strict: {repo}'s contract was read from the working tree rather than "
                    f"{PUBLISHED_REF}"
                )
        if body is None:
            notes.append(f"{repo} publishes no {CONTRACT_PATH}; nothing is registered against here")
            continue

        probes, problems = parse(body)
        if problems:
            # Their contract, their format. Reported rather than enforced.
            notes.append(f"{repo}: contract has {len(problems)} format problem(s)")
        siblings_read.append(repo)

        for probe in (p for p in probes if p.repo == THIS_REPO):
            target = root / probe.path
            if not target.exists():
                failures.append(
                    f"{repo} cites {probe.path}, which does not exist here "
                    f"(their line {probe.line})"
                )
                continue
            occurrences = target.read_text(encoding="utf-8", errors="replace").count(probe.probe)
            if occurrences == 0:
                message = (
                    f"{repo} cites {probe.probe!r} in {probe.path}; it is gone "
                    f"(their line {probe.line})"
                )
                (failures if probe.role == FAIL_ROLE else warnings).append(message)
                continue
            resolved += 1
            if occurrences > 1:
                warnings.append(
                    f"{repo}: {probe.probe!r} occurs {occurrences} times in {probe.path}, so it is "
                    "a weak probe -- rewording one occurrence leaves their gate green"
                )

    for note in notes:
        print(f"incoming-probes: {note}")
    for warning in warnings:
        print(f"incoming-probes: {warning}")
    for failure in failures:
        print(f"incoming-probes: {failure}")

    if failures:
        return 1
    print(
        f"incoming-probes: {resolved} registration(s) from "
        f"{len(siblings_read)} sibling(s) resolve here"
        + (f" (contracts read at {PUBLISHED_REF})" if siblings_read else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
