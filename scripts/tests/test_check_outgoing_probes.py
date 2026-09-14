"""Tests for tools/check_outgoing_probes.py.

**Why these exist.** The checker read the sibling's working tree, and one direction of that mistake
passes silently: a probe satisfied by a sentence that exists only in somebody's uncommitted edit
reports green, while the repository everyone else reads does not contain it. The sibling that owns
the cited claims found the same hole on its own side. A hand-run `git show` is not the gate, so the
tests here drive the gate against checkouts built for the purpose.

Each test is written so that reverting the fix makes it fail for the stated reason, not merely fail.
"""

from __future__ import annotations

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


def make_checkout(root: Path, committed: str | None, worktree: str | None) -> Path:
    """A checkout with `origin/main`, whose committed and working-tree bodies can differ.

    `origin/main` is made by cloning, so the ref is real rather than a hand-written file: the
    checker asks git for it and a fabricated ref would not answer the same way.
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
        target = seed / CITED
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(committed, encoding="utf-8")
        git(seed, "add", CITED)
    else:
        (seed / "README.md").write_text("placeholder\n", encoding="utf-8")
        git(seed, "add", "README.md")
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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(worktree, encoding="utf-8")
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
