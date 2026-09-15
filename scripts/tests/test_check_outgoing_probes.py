"""Tests for tools/check_outgoing_probes.py.

**Why these exist.** The checker read the sibling's working tree, and one direction of that mistake
passes silently: a probe satisfied by a sentence that exists only in somebody's uncommitted edit
reports green, while the repository everyone else reads does not contain it. The sibling that owns
the cited claims found the same hole on its own side. A hand-run `git show` is not the gate, so the
tests here drive the gate against checkouts built for the purpose.

Each test is written so that reverting the fix makes it fail for the stated reason, not merely fail.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = ROOT / "tools" / "check_outgoing_probes.py"
REPO = "S3-Burst-on-ONTAP-Files"
CITED = "docs/ja/claim.md"
CLAIM = "上限は 1 フローの容量ではない"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(root: Path, path: str, body: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def make_checkout(
    root: Path,
    committed: str | None,
    worktree: str | None,
    also_committed: dict[str, str] | None = None,
    also_worktree: dict[str, str] | None = None,
) -> Path:
    """A checkout with `origin/main`, whose committed and working-tree bodies can differ.

    `origin/main` is made by cloning, so the ref is real rather than a hand-written file: the
    checker asks git for it and a fabricated ref would not answer the same way.

    `also_committed` / `also_worktree` place further files on either side, which is how the
    supersession registry gets tested at both the published ref and in the working tree only.
    """
    upstream = root / "upstream.git"
    upstream.mkdir()
    git(upstream, "init", "--quiet", "--bare", "--initial-branch=main")

    seed = root / "seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "--initial-branch=main")
    git(seed, "config", "user.email", "test@example.invalid")
    git(seed, "config", "user.name", "test")
    if committed is not None:
        write(seed, CITED, committed)
        git(seed, "add", CITED)
    else:
        (seed / "README.md").write_text("placeholder\n", encoding="utf-8")
        git(seed, "add", "README.md")
    for path, body in (also_committed or {}).items():
        write(seed, path, body)
        git(seed, "add", path)
    git(seed, "commit", "--quiet", "-m", "seed")
    git(seed, "remote", "add", "origin", str(upstream))
    git(seed, "push", "--quiet", "origin", "main")

    checkout = root / REPO
    git(root, "clone", "--quiet", str(upstream), REPO)

    target = checkout / CITED
    if worktree is None:
        if target.exists():
            target.unlink()
    else:
        write(checkout, CITED, worktree)
    for path, body in (also_worktree or {}).items():
        write(checkout, path, body)
    return checkout


def make_contract(root: Path, role: str = "retraction") -> Path:
    contract = root / "contract.txt"
    contract.write_text(f"{REPO}\t{CITED}\t{role}\t{CLAIM}\n", encoding="utf-8")
    return contract


def run(sibling_root: Path, contract: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--contract", str(contract)],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "SIBLING_ROOT": str(sibling_root),
        },
    )


def test_unpushed_addition_does_not_satisfy_a_probe(tmp_path: Path) -> None:
    """The direction that used to pass silently.

    The claim exists only in the working tree. Reading that tree reports green while the published
    repository does not carry the sentence the citation rests on.
    """
    make_checkout(tmp_path, committed="nothing relevant here\n", worktree=f"**{CLAIM}。**\n")
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 1, result.stdout
    assert "no longer contains" in result.stdout
    assert "origin/main" in result.stdout


def test_unpushed_deletion_does_not_break_a_probe(tmp_path: Path) -> None:
    """The mirror direction: an editor mid-rewrite is not a retraction."""
    make_checkout(tmp_path, committed=f"**{CLAIM}。**\n", worktree="mid-rewrite\n")
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert f"read {REPO} at origin/main" in result.stdout


def test_absent_path_at_the_published_ref_is_reported_as_absent(tmp_path: Path) -> None:
    """A file that is not in the published repository is a failure, not a fallback."""
    make_checkout(tmp_path, committed=None, worktree=f"**{CLAIM}。**\n")
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 1, result.stdout
    assert "does not exist at origin/main" in result.stdout
    assert "fell back" not in result.stdout


def test_checkout_without_the_published_ref_falls_back_and_says_so(tmp_path: Path) -> None:
    """No `origin/main` is a different question from a missing path, and must be visible."""
    checkout = tmp_path / REPO
    (checkout / "docs" / "ja").mkdir(parents=True)
    (checkout / CITED).write_text(f"**{CLAIM}。**\n", encoding="utf-8")
    git(checkout, "init", "--quiet", "--initial-branch=main")

    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "fell back to the working tree" in result.stdout
    assert "weaker evidence" in result.stdout
    assert "read" not in result.stdout.split("fell back")[0].split("\n")[-1]


def test_reread_warns_where_retraction_fails(tmp_path: Path) -> None:
    make_checkout(tmp_path, committed="reworded\n", worktree="reworded\n")
    warned = run(tmp_path, make_contract(tmp_path, role="reread"))
    assert warned.returncode == 0, warned.stdout
    assert "reread:" in warned.stdout

    failed = run(tmp_path, make_contract(tmp_path, role="retraction"))
    assert failed.returncode == 1, failed.stdout


def test_the_real_contract_is_sorted_and_well_formed() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--selftest"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("flag", ["--contract"])
def test_missing_contract_is_not_a_failure(tmp_path: Path, flag: str) -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), flag, str(tmp_path / "absent.txt")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nothing cited" in result.stdout


def run_strict(sibling_root: Path, contract: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--contract", str(contract), "--strict"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "SIBLING_ROOT": str(sibling_root),
        },
    )


def test_strict_fails_on_a_missing_checkout(tmp_path: Path) -> None:
    """The shape CI must not pass in: nothing was checked and the exit code said fine."""
    contract = make_contract(tmp_path)
    lenient = run(tmp_path, contract)
    assert lenient.returncode == 0
    assert "A skip is not a pass" in lenient.stdout

    strict = run_strict(tmp_path, contract)
    assert strict.returncode == 1, strict.stdout
    assert "--strict" in strict.stdout


def test_strict_fails_when_the_read_fell_back(tmp_path: Path) -> None:
    checkout = tmp_path / REPO
    (checkout / "docs" / "ja").mkdir(parents=True)
    (checkout / CITED).write_text(f"**{CLAIM}。**\n", encoding="utf-8")
    git(checkout, "init", "--quiet", "--initial-branch=main")

    contract = make_contract(tmp_path)
    assert run(tmp_path, contract).returncode == 0

    strict = run_strict(tmp_path, contract)
    assert strict.returncode == 1, strict.stdout
    assert "working tree rather than origin/main" in strict.stdout


def test_strict_passes_when_everything_was_read_at_the_published_ref(tmp_path: Path) -> None:
    make_checkout(tmp_path, committed=f"**{CLAIM}。**\n", worktree=f"**{CLAIM}。**\n")
    strict = run_strict(tmp_path, make_contract(tmp_path))
    assert strict.returncode == 0, strict.stdout
    assert "--strict" not in strict.stdout


def test_a_probe_matching_twice_is_reported_as_weak(tmp_path: Path) -> None:
    """Weak anchor, not a withdrawn claim: reported, and the run still passes.

    Hand-counting occurrences is what caught two weak probes in this exchange, and hand-counting
    held only because somebody remembered to do it.
    """
    body = f"**{CLAIM}。**\n\nあとで同じ文が出ます。{CLAIM}\n"
    make_checkout(tmp_path, committed=body, worktree=body)
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "occurs 2 times" in result.stdout
    assert "leaves this check green" in result.stdout


def test_a_single_occurrence_is_not_reported_as_weak(tmp_path: Path) -> None:
    """The boundary. Written so that removing the detection leaves this test passing -- if it
    failed too, the pair would only prove that the checker prints something."""
    body = f"**{CLAIM}。**\n"
    make_checkout(tmp_path, committed=body, worktree=body)
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "occurs" not in result.stdout
    assert "weak" not in result.stdout


def test_weakness_is_reported_for_a_reread_probe_too(tmp_path: Path) -> None:
    """The count is a property of the anchor, so it does not depend on the role."""
    body = f"{CLAIM}\n{CLAIM}\n{CLAIM}\n"
    make_checkout(tmp_path, committed=body, worktree=body)
    result = run(tmp_path, make_contract(tmp_path, role="reread"))
    assert result.returncode == 0, result.stdout
    assert "occurs 3 times" in result.stdout


REGISTRY = "docs/agent/superseded-claims.txt"
SUPERSEDING_ANCHOR = "#新しい実測"


def registry(path: str, string: str, anchor: str = SUPERSEDING_ANCHOR) -> str:
    return f"# owner-declared supersessions\n{path}\t{string}\t{anchor}\n"


def test_a_superseded_claim_that_is_still_present_is_reported(tmp_path: Path) -> None:
    """The hole a probe cannot see.

    The sentence is where it was registered, so presence is satisfied and the check stays green,
    while the finding underneath it has been overturned. This side missed that twice in two rounds
    and both times only by reading the sibling's new section. Reported rather than failed: the
    citation may still be usable once someone reads the superseding section.
    """
    body = f"**{CLAIM}。**\n"
    make_checkout(
        tmp_path,
        committed=body,
        worktree=body,
        also_committed={REGISTRY: registry(CITED, CLAIM)},
    )
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "declare it superseded" in result.stdout
    assert SUPERSEDING_ANCHOR in result.stdout


def test_a_claim_absent_from_the_registry_is_not_reported(tmp_path: Path) -> None:
    """The boundary. Written so that removing the detection leaves this test passing -- if it failed
    too, the pair would only show that the checker prints something."""
    body = f"**{CLAIM}。**\n"
    make_checkout(
        tmp_path,
        committed=body,
        worktree=body,
        also_committed={REGISTRY: registry(CITED, "別の主張")},
    )
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "superseded" not in result.stdout


def test_a_missing_supersession_registry_is_not_an_error(tmp_path: Path) -> None:
    """Most repositories publish no registry, and that is the normal case rather than a fault."""
    body = f"**{CLAIM}。**\n"
    make_checkout(tmp_path, committed=body, worktree=body)
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "superseded" not in result.stdout


def test_an_unpushed_registry_entry_does_not_raise_a_supersession(tmp_path: Path) -> None:
    """The registry is read the same way the cited files are: at `origin/main`.

    An entry that exists only in somebody's working tree is an editing state, not a declaration the
    owner has published, and reading it here would report a supersession nobody can look up.
    """
    body = f"**{CLAIM}。**\n"
    make_checkout(
        tmp_path,
        committed=body,
        worktree=body,
        also_worktree={REGISTRY: registry(CITED, CLAIM)},
    )
    result = run(tmp_path, make_contract(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "superseded" not in result.stdout


def test_the_shape_is_recomputed_from_the_registrations(tmp_path: Path) -> None:
    """The premise behind blocking is printed, not stored."""
    body = f"**{CLAIM}。**\n"
    make_checkout(tmp_path, committed=body, worktree=body)
    contract = tmp_path / "contract.txt"
    rows = sorted([CLAIM, CLAIM[:12]])
    contract.write_text(
        "".join(f"{REPO}\t{CITED}\tretraction\t{row}\n" for row in rows), encoding="utf-8"
    )
    result = run(tmp_path, contract)
    assert result.returncode == 0, result.stdout
    assert "shape: 2 registration(s) across 1 file(s), 2 in the largest" in result.stdout


def test_the_blocking_rationale_carries_no_hand_written_count() -> None:
    """The premise went stale once already.

    The document explains why this check blocks. Writing the number there means the explanation
    outlives the shape it rests on, so the number has to come from the checker.
    """
    note = (ROOT / "docs" / "agent" / "cross-repo-block-performance.md").read_text(encoding="utf-8")
    section = note.split("## 2 方向のゲートと、ブロックの扱い", 1)
    assert len(section) == 2, "the section explaining the blocking decision is gone"
    stale = re.findall(r"引用が \d+ 件|登録が \d+ 件|\d+ 件の登録", section[1])
    assert not stale, f"hand-written registration counts in the rationale: {stale}"
