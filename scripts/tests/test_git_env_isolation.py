"""Git calls made by the gates must not inherit the running hook's git environment.

git exports GIT_DIR / GIT_INDEX_FILE to hooks, and they override `cwd` in every git
subprocess. Measured from a linked worktree: a test that ran `git init` / `git add` in a
tmp repo without clearing them staged a fixture AGENTS.md into the pending commit,
overwrote user.name in .git/config and set core.bare=true.

Two layers, both checked here:
- the hooks run the gates with GIT_* removed (covers call sites not written yet);
- each git subprocess in scripts/ and tools/ passes an explicit `env=` (covers running
  a test or checker directly from inside some other git operation).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = (REPO / ".githooks" / "pre-commit", REPO / ".githooks" / "pre-push")
CLEARED = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")


def git_calls_without_env(source: str) -> list[int]:
    """Line numbers of subprocess calls whose argv starts with "git" and that pass no env=."""
    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"run", "check_call", "check_output", "Popen", "call"}:
            continue
        argv = node.args[0]
        if not isinstance(argv, ast.List) or not argv.elts:
            continue
        first = argv.elts[0]
        if not (isinstance(first, ast.Constant) and first.value == "git"):
            continue
        if not any(kw.arg == "env" for kw in node.keywords):
            offenders.append(node.lineno)
    return offenders


def test_detector_flags_a_git_call_without_env() -> None:
    bad = 'import subprocess\nsubprocess.run(["git", "add", "x"], cwd=p, check=True)\n'
    assert git_calls_without_env(bad) == [2]


def test_detector_passes_a_git_call_with_env() -> None:
    good = 'import subprocess\nsubprocess.run(["git", "add", "x"], cwd=p, env=e)\n'
    assert git_calls_without_env(good) == []


def test_detector_ignores_non_git_argv() -> None:
    other = 'import subprocess\nsubprocess.run([sys.executable, "x.py"], check=True)\n'
    assert git_calls_without_env(other) == []


@pytest.mark.parametrize("hook", HOOKS, ids=lambda p: p.name)
def test_hook_runs_the_gates_without_git_env(hook: Path) -> None:
    lines = [ln for ln in hook.read_text(encoding="utf-8").splitlines() if "make gates" in ln]
    runs = [ln for ln in lines if not ln.lstrip().startswith(("#", "echo"))]
    assert runs, f"{hook.name}: no line runs make gates"
    for line in runs:
        missing = [var for var in CLEARED if f"-u {var}" not in line]
        assert not missing, f"{hook.name}: make gates runs with {missing} inherited: {line.strip()}"


def test_every_git_subprocess_passes_env() -> None:
    offenders = []
    for path in sorted([*(REPO / "scripts").rglob("*.py"), *(REPO / "tools").rglob("*.py")]):
        for lineno in git_calls_without_env(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO)}:{lineno}")
    assert not offenders, "git subprocess without env= (inherits a hook's GIT_DIR): " + ", ".join(
        offenders
    )
