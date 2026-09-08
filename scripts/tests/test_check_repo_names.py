"""The repository-name guard must reject stale names, not merely accept current ones.

Three outcomes are covered explicitly:

  block         — exit 1: a name that is not the repository's current name
  cannot judge  — exit 2: the API could not be reached for some name
  allow         — exit 0: every name resolved and every name is current

**A case-only rename and a slug rename are separate families and both are tested.**
GitHub resolves repository names case-insensitively and serves the requested casing
with 200, so a check that compares the final URL after redirects is silent on the
case-only family. The upstream version of this check was, while passing a break test
that happened to use a slug rename. Proving a detector fires on one member of a
family says nothing about the rest of it.

The network cases skip rather than fail when the API is unreachable or rate-limited.
"Cannot judge" is not "did not detect", and a test that conflates them reports an
outage as a defect.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "check_repo_names.py"

sys.path.insert(0, str(SCRIPT.parent))
import check_repo_names as names  # noqa: E402

# Old names of sibling repositories, one per rename family. Both still resolve.
CASE_ONLY = "vmware-migration-ec2-ontap"  # now VMware-Migration-EC2-ONTAP
CASE_ONLY_SIBLING = "ontap-edge-to-cloud-ai"  # now ONTAP-Edge-to-Cloud-AI
SLUG_RENAME = "fsxn-lakehouse-integrations"  # now FSx-for-ONTAP-Lakehouse-Integrations


def run_gate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


@contextmanager
def scratch_prose(body: str) -> Iterator[Path]:
    """Write a scratch document inside the repository, then remove it.

    The scanner walks the real tree, so the fixture has to live in it for the
    real path to be exercised. `finally` matters: a leftover scratch file would
    fail every later run of the gate for a reason unrelated to the repository.
    """
    path = REPO_ROOT / "docs" / "ja" / "_scratch-test-repo-name.md"
    path.write_text(body, encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def skip_if_unjudgeable(result: subprocess.CompletedProcess[str]) -> None:
    if "cannot resolve" in (result.stdout + result.stderr):
        pytest.skip("GitHub API unreachable or rate-limited")


# ---------------------------------------------------------------- offline


def test_selftest_passes() -> None:
    """The extraction half must be provable without the network."""
    result = run_gate("--selftest")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("https://github.com/Yoshiki0705/Repo-One", {"Repo-One"}),
        ("git clone https://github.com/Yoshiki0705/Repo-One.git", {"Repo-One"}),
        ("[x](https://github.com/Yoshiki0705/Repo-One)", {"Repo-One"}),
        ("https://github.com/Yoshiki0705/Repo-One/blob/main/a.md", {"Repo-One"}),
        ("https://github.com/other-owner/Repo-One", set()),
    ],
)
def test_reference_extraction(text: str, want: set[str]) -> None:
    assert names.references(text) == want


def test_clone_url_suffix_is_stripped() -> None:
    """`.git` left on the name makes the API 404 and a good name read as unresolvable."""
    assert names.normalize("Repo-One.git") == "Repo-One"


def test_fenced_block_is_scanned() -> None:
    """A stale clone URL inside a fence is the worst kind: it gets run.

    This is the deliberate difference from the citation check it was ported from,
    which blanks fences so that an example link is not read as a citation.
    """
    fenced = "```bash\ngit clone https://github.com/Yoshiki0705/Repo-One.git\n```"
    assert names.references(fenced) == {"Repo-One"}


# ---------------------------------------------------------------- block


@pytest.mark.parametrize(
    "stale",
    [
        pytest.param(CASE_ONLY, id="case-only"),
        pytest.param(CASE_ONLY_SIBLING, id="case-only-sibling"),
        pytest.param(SLUG_RENAME, id="slug-rename"),
    ],
)
def test_stale_name_is_rejected(stale: str) -> None:
    body = f"# scratch\n\nSee https://github.com/Yoshiki0705/{stale} for context.\n"
    with scratch_prose(body):
        result = run_gate()
        skip_if_unjudgeable(result)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "is not the current name" in result.stdout


# ---------------------------------------------------------------- cannot judge


def test_unresolvable_name_is_not_reported_as_stale() -> None:
    """A name the API cannot answer for must not be reported as an old name.

    A gate that reports an outage as a finding is a gate people learn to ignore.
    """
    body = "# scratch\n\nhttps://github.com/Yoshiki0705/this-repo-does-not-exist-abcdef\n"
    with scratch_prose(body):
        result = run_gate()
        assert result.returncode == 2, result.stdout + result.stderr
        assert "could not judge" in result.stderr
        assert "is not the current name" not in result.stdout


# ---------------------------------------------------------------- allow


def test_real_repository_passes() -> None:
    """Checked last. A guard only ever observed passing is not known to work."""
    result = run_gate()
    skip_if_unjudgeable(result)
    assert result.returncode == 0, result.stdout + result.stderr
