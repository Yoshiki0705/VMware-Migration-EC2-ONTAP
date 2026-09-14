"""Tests for tools/check_incoming_probes.py.

**Why these exist.** Two siblings register exact substrings of this repository's documents. Nothing
here checked that those sentences survive an edit made here; the discovery happened on the other
side or in a message. This is the direction where the failure is caused by the diff in front of you,
so it is the direction that blocks.

The reads are asymmetric and each test pins one half: the sibling's contract is read at
`origin/main` (a registration living only in someone's working tree is not a commitment), while this
repository's files are read from the working tree (the question is whether the edit in progress still
satisfies what was published).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHECKER = ROOT / "tools" / "check_incoming_probes.py"
SIBLING = "S3-Burst-on-ONTAP-Files"
CONTRACT_PATH = "docs/agent/cross-repo-probe-contract.txt"
CITED = "docs/ja/tco-comparison.md"
CLAIM = "容量単価だけで FSx for ONTAP を選ぶ根拠は、ブロックでは成立しません"
ENV_PATH = "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def registration(role: str = "retraction", claim: str = CLAIM) -> str:
    return f"VMware-Migration-EC2-ONTAP\t{CITED}\t{role}\t{claim}\n"


def make_sibling(root: Path, committed: str | None, worktree: str | None = None) -> Path:
    """A sibling checkout with a real `origin/main`, whose published contract can differ.

    The ref comes from cloning rather than from a hand-written file: the checker asks git for it.
    """
    upstream = root / "upstream.git"
    upstream.mkdir()
    git(upstream, "init", "--quiet", "--bare", "--initial-branch=main")

    seed = root / "seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "--initial-branch=main")
    git(seed, "config", "user.email", "test@example.invalid")
    git(seed, "config", "user.name", "test")
    contract = seed / CONTRACT_PATH
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(committed or "", encoding="utf-8")
    git(seed, "add", CONTRACT_PATH)
    git(seed, "commit", "--quiet", "-m", "seed")
    git(seed, "remote", "add", "origin", str(upstream))
    git(seed, "push", "--quiet", "origin", "main")

    git(root, "clone", "--quiet", str(upstream), SIBLING)
    checkout = root / SIBLING
    if worktree is not None:
        (checkout / CONTRACT_PATH).write_text(worktree, encoding="utf-8")
    return checkout


def make_here(root: Path, body: str) -> Path:
    """A stand-in for this repository, with the cited file carrying `body`."""
    here = root / "here"
    (here / "docs" / "ja").mkdir(parents=True)
    (here / CITED).write_text(body, encoding="utf-8")
    return here


def run(sibling_root: Path, here: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--repo-root", str(here), *flags],
        capture_output=True,
        text=True,
        env={"PATH": ENV_PATH, "SIBLING_ROOT": str(sibling_root)},
    )


def test_a_present_claim_resolves(tmp_path: Path) -> None:
    make_sibling(tmp_path, committed=registration())
    here = make_here(tmp_path, f"**{CLAIM}。**\n")
    result = run(tmp_path, here)
    assert result.returncode == 0, result.stdout
    assert "1 registration(s) from 1 sibling(s) resolve here" in result.stdout
    assert "contracts read at origin/main" in result.stdout


def test_rewording_the_cited_sentence_fails(tmp_path: Path) -> None:
    """The whole point: an edit here that removes their basis stops the run."""
    make_sibling(tmp_path, committed=registration())
    here = make_here(tmp_path, "この節は書き直しました。\n")
    result = run(tmp_path, here)
    assert result.returncode == 1, result.stdout
    assert SIBLING in result.stdout
    assert CLAIM in result.stdout
    assert "it is gone" in result.stdout


def test_a_registration_only_in_their_working_tree_is_not_a_commitment(tmp_path: Path) -> None:
    """Their unpushed edit does not bind this repository."""
    make_sibling(tmp_path, committed="", worktree=registration())
    here = make_here(tmp_path, "何も引かれていません。\n")
    result = run(tmp_path, here)
    assert result.returncode == 0, result.stdout
    assert "0 registration(s)" in result.stdout


def test_multiple_occurrences_are_reported_as_weak(tmp_path: Path) -> None:
    make_sibling(tmp_path, committed=registration())
    here = make_here(tmp_path, f"{CLAIM}\n\n{CLAIM}\n")
    result = run(tmp_path, here)
    assert result.returncode == 0, result.stdout
    assert "occurs 2 times" in result.stdout
    assert "weak probe" in result.stdout


def test_reread_warns_where_retraction_fails(tmp_path: Path) -> None:
    make_sibling(tmp_path, committed=registration(role="reread"))
    here = make_here(tmp_path, "書き直しました。\n")
    result = run(tmp_path, here)
    assert result.returncode == 0, result.stdout
    assert "it is gone" in result.stdout


def test_a_cited_file_that_does_not_exist_here_fails(tmp_path: Path) -> None:
    make_sibling(tmp_path, committed=registration())
    here = tmp_path / "here"
    here.mkdir()
    result = run(tmp_path, here)
    assert result.returncode == 1, result.stdout
    assert "does not exist here" in result.stdout


def test_strict_fails_on_a_missing_sibling_checkout(tmp_path: Path) -> None:
    here = make_here(tmp_path, f"{CLAIM}\n")
    lenient = run(tmp_path, here)
    assert lenient.returncode == 0
    assert "A skip is not a pass" in lenient.stdout

    strict = run(tmp_path, here, "--strict")
    assert strict.returncode == 1, strict.stdout
    assert "--strict" in strict.stdout


def test_selftest_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--selftest"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout
