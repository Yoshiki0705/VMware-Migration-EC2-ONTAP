#!/usr/bin/env python3
"""Keep always-loaded agent context small, thin, reachable, and published.

Four failures this guards against, all of which are silent:

1. AGENTS.md grows. It is read on every turn and cannot be made conditional, so
   work-specific material in it is paid for on every unrelated turn.
2. A .kiro/steering loader stops being a loader. `.kiro/` is gitignored here
   (BLEA-style), so prose that migrates into a loader disappears from the
   published repository while still consuming context.
3. An index entry points at a file that does not exist. Nothing errors; the
   agent simply never reads the knowledge and behaves as if it does not exist.
4. An index entry points at a real file that git does not track. Readers on
   GitHub cannot see it, so the documentation is effectively private.

Three outcomes, mirroring the hook guards:
  block (exit 1) — over the hard cap, unreachable, or untracked
  ask   (exit 0 + warning) — within the cap but past the warn threshold
  allow (exit 0, silent) — healthy

Run via `make context-budget` or `make drift`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# AGENTS.md is read every turn. The cap is a budget, not a style preference.
AGENTS_WARN_BYTES = 3072
AGENTS_BLOCK_BYTES = 4096

# A steering file under .kiro/ that is always or auto included should say when to
# read something, not be the something.
LOADER_WARN_BYTES = 1024
LOADER_BLOCK_BYTES = 2048

ALWAYS_LOADED_INCLUSIONS = {"always", "auto"}

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)")
BACKTICK_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|sh|ya?ml|json|toml|txt))`")
INCLUSION_RE = re.compile(r"^inclusion:\s*(\S+)\s*$", re.MULTILINE)
FRONT_MATTER_KEY_RE = re.compile(r"^(name|description):\s*(.+)$", re.MULTILINE)

# Referenced paths that are expected to be untracked, so the tracked-status check
# does not fire on them.
UNTRACKED_BY_DESIGN_PREFIXES = (".kiro/", ".private/", ".venv/")


@dataclass
class Report:
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocks


def tracked_files(root: Path) -> set[str]:
    """Paths git tracks. Empty set when git is unavailable, which skips the check."""
    # Strip inherited git-location variables. Under a pre-commit hook git exports
    # GIT_DIR / GIT_INDEX_FILE, which override cwd: "ls-files" would then list the
    # hook's repository instead of `root`, and an untracked target in `root` would
    # pass silently.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {line for line in result.stdout.splitlines() if line}


def front_matter_inclusion(text: str) -> str:
    """`always` is the documented default when no inclusion key is present."""
    if not text.startswith("---"):
        return "always"
    end = text.find("\n---", 3)
    head = text[3:end] if end != -1 else text
    match = INCLUSION_RE.search(head)
    return match.group(1) if match else "always"


def referenced_paths(text: str) -> set[str]:
    found = set(MD_LINK_RE.findall(text)) | set(BACKTICK_PATH_RE.findall(text))
    return {path for path in found if not path.startswith(("http://", "https://", "mailto:", "#"))}


def check_agents_file(root: Path, report: Report) -> None:
    path = root / "AGENTS.md"
    if not path.is_file():
        report.blocks.append("AGENTS.md がありません。")
        return
    size = path.stat().st_size
    if size > AGENTS_BLOCK_BYTES:
        report.blocks.append(
            f"AGENTS.md が {size} バイトで上限 {AGENTS_BLOCK_BYTES} を超えています。"
            "毎ターン読み込まれるので、作業依存の記述は docs/agent/ に移して索引 1 行にしてください。"
        )
    elif size > AGENTS_WARN_BYTES:
        report.warnings.append(
            f"AGENTS.md が {size} バイト（警告閾値 {AGENTS_WARN_BYTES}、上限 {AGENTS_BLOCK_BYTES}）。"
        )


def check_loaders(root: Path, report: Report) -> None:
    directory = root / ".kiro" / "steering"
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        inclusion = front_matter_inclusion(text)
        if inclusion not in ALWAYS_LOADED_INCLUSIONS:
            continue
        size = len(text.encode("utf-8"))
        where = f".kiro/steering/{path.name}"
        if size > LOADER_BLOCK_BYTES:
            report.blocks.append(
                f"{where} が {size} バイトで上限 {LOADER_BLOCK_BYTES} を超えています"
                f"（inclusion: {inclusion}）。.kiro/ は非公開なので本文は追跡対象へ移してください。"
            )
        elif size > LOADER_WARN_BYTES:
            report.warnings.append(
                f"{where} が {size} バイト（警告閾値 {LOADER_WARN_BYTES}）。ローダーとしては厚めです。"
            )
        if inclusion == "auto":
            keys = dict(FRONT_MATTER_KEY_RE.findall(text))
            missing = [k for k in ("name", "description") if not keys.get(k)]
            if missing:
                report.blocks.append(
                    f"{where}: inclusion:auto に {' と '.join(missing)} がありません。登録されず一度も読み込まれません。"
                )


def check_index_targets(root: Path, report: Report) -> None:
    sources = [root / "AGENTS.md"]
    steering = root / ".kiro" / "steering"
    if steering.is_dir():
        sources.extend(sorted(steering.glob("*.md")))

    tracked = tracked_files(root)
    for source in sources:
        if not source.is_file():
            continue
        rel_source = source.relative_to(root).as_posix()
        for ref in sorted(referenced_paths(source.read_text(encoding="utf-8"))):
            if any(ch in ref for ch in "*?"):
                continue  # glob, not a single file
            target = (root / ref).resolve()
            if not target.exists():
                report.blocks.append(
                    f"{rel_source} が参照する {ref} が存在しません。索引が指す先に知識がありません。"
                )
                continue
            if ref.startswith(UNTRACKED_BY_DESIGN_PREFIXES):
                continue
            if tracked and ref not in tracked:
                report.blocks.append(
                    f"{rel_source} が参照する {ref} が git 未追跡です。公開リポジトリからは読めません。"
                )


def run(root: Path) -> Report:
    report = Report()
    check_agents_file(root, report)
    check_loaders(root, report)
    check_index_targets(root, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(REPO_ROOT), help="監査するリポジトリのルート")
    args = parser.parse_args()

    report = run(Path(args.root).resolve())

    for warning in report.warnings:
        print(f"warning: {warning}")
    for block in report.blocks:
        print(f"error: {block}")

    if not report.ok:
        print(
            "常時ロードコンテキストの予算超過です。"
            "本文は追跡対象の docs/agent/ に置き、.kiro/steering/ は「いつ読むか」だけにしてください。"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
