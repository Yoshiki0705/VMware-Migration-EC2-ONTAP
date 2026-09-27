"""The context-budget guard must reject bad input, not merely accept good input.

Three outcomes are covered explicitly:
  block  — exit 1: over the hard cap, an index target missing, or git-untracked
  ask    — exit 0 with a warning: past the warn threshold, under the cap
  allow  — exit 0, no output

The real repository is checked last. A guard that has only ever been observed
passing is not known to work.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_agent_context_budget.py"

sys.path.insert(0, str(SCRIPT.parent))
import check_agent_context_budget as budget  # noqa: E402

LOADER_FRONT_MATTER = "---\ninclusion: auto\nname: fixture\ndescription: fixture loader\n---\n"


def make_repo(
    tmp_path: Path,
    *,
    agents_body: str = "index only\n",
    loader_body: str | None = None,
    git_init: bool = False,
) -> Path:
    (tmp_path / "AGENTS.md").write_text(agents_body, encoding="utf-8")
    if loader_body is not None:
        steering = tmp_path / ".kiro" / "steering"
        steering.mkdir(parents=True)
        (steering / "fixture.md").write_text(loader_body, encoding="utf-8")
    if git_init:
        # Strip inherited git-location variables. Under a pre-commit hook git
        # exports GIT_DIR / GIT_INDEX_FILE; without clearing them this "git add
        # AGENTS.md" stages the fixture's AGENTS.md into the real repository's
        # index instead of the throwaway one, corrupting the pending commit.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)  # noqa: S603,S607
        subprocess.run(["git", "add", "AGENTS.md"], cwd=tmp_path, check=True, env=env)  # noqa: S603,S607
    return tmp_path


# ---------------------------------------------------------------- allow


def test_allow_healthy_repo_is_silent(tmp_path: Path) -> None:
    report = budget.run(make_repo(tmp_path))
    assert report.ok
    assert report.warnings == []


# ---------------------------------------------------------------- ask


def test_ask_agents_file_past_warn_threshold(tmp_path: Path) -> None:
    body = "x" * (budget.AGENTS_WARN_BYTES + 10)
    report = budget.run(make_repo(tmp_path, agents_body=body))
    assert report.ok, "警告閾値ではブロックしない"
    assert any("AGENTS.md" in w for w in report.warnings)


def test_ask_loader_past_warn_threshold(tmp_path: Path) -> None:
    loader = LOADER_FRONT_MATTER + "y" * (budget.LOADER_WARN_BYTES + 10)
    report = budget.run(make_repo(tmp_path, loader_body=loader))
    assert report.ok
    assert any("fixture.md" in w for w in report.warnings)


# ---------------------------------------------------------------- block


def test_block_agents_file_over_hard_cap(tmp_path: Path) -> None:
    body = "x" * (budget.AGENTS_BLOCK_BYTES + 1)
    report = budget.run(make_repo(tmp_path, agents_body=body))
    assert not report.ok
    assert any("AGENTS.md" in b for b in report.blocks)


def test_block_missing_agents_file(tmp_path: Path) -> None:
    report = budget.run(tmp_path)
    assert not report.ok


def test_block_loader_carrying_the_body(tmp_path: Path) -> None:
    loader = LOADER_FRONT_MATTER + "z" * (budget.LOADER_BLOCK_BYTES + 1)
    report = budget.run(make_repo(tmp_path, loader_body=loader))
    assert not report.ok
    assert any("fixture.md" in b for b in report.blocks)


def test_block_auto_loader_without_name_and_description(tmp_path: Path) -> None:
    loader = "---\ninclusion: auto\n---\n# body\n"
    report = budget.run(make_repo(tmp_path, loader_body=loader))
    assert not report.ok
    assert any("inclusion:auto" in b for b in report.blocks)


def test_block_index_target_that_does_not_exist(tmp_path: Path) -> None:
    body = "see [conventions](docs/agent/project-conventions.md)\n"
    report = budget.run(make_repo(tmp_path, agents_body=body))
    assert not report.ok
    assert any("存在しません" in b for b in report.blocks)


def test_block_index_target_that_git_does_not_track(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        agents_body="see [notes](docs/agent/notes.md)\n",
        git_init=True,
    )
    target = repo / "docs" / "agent" / "notes.md"
    target.parent.mkdir(parents=True)
    target.write_text("body\n", encoding="utf-8")

    report = budget.run(repo)
    assert not report.ok, "実在するが未追跡のファイルはブロックする"
    assert any("未追跡" in b for b in report.blocks)


def test_kiro_paths_are_exempt_from_the_tracked_check(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        agents_body="loader: `.kiro/steering/fixture.md`\n",
        loader_body=LOADER_FRONT_MATTER + "thin\n",
        git_init=True,
    )
    report = budget.run(repo)
    assert report.ok, f".kiro/ は設計上未追跡: {report.blocks}"


# ---------------------------------------------------------------- exit codes


@pytest.mark.parametrize(
    ("agents_body", "expected"),
    [("index only\n", 0), ("x" * (budget.AGENTS_BLOCK_BYTES + 1), 1)],
)
def test_exit_code_matches_outcome(tmp_path: Path, agents_body: str, expected: int) -> None:
    repo = make_repo(tmp_path, agents_body=agents_body)
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected, result.stdout


# ---------------------------------------------------------------- real repo


def test_this_repository_is_within_budget() -> None:
    report = budget.run(REPO_ROOT)
    assert report.ok, "\n".join(report.blocks)
