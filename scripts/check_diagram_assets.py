#!/usr/bin/env python3
"""Fail when the committed architecture diagrams have drifted from their build.

Why this exists
---------------
`tools/build_diagrams.py` already refuses to finish on a missing icon, an untranslated
label, unparseable XML or a cell that never landed. None of that runs in CI: the build
needs the AWS Architecture Icons package, which is deliberately not in this repository,
and the draw.io desktop app to export. So every one of those guarantees holds only on the
machine that last ran the build, and nothing notices when the committed artifacts stop
matching it.

What is checked here is the subset that needs neither icons nor a renderer:

  1. No icon-library file has been committed. AWS licenses the assets for use in a
     diagram, not for redistribution, so `Arch_*`, `Res_*` and the package directory must
     never appear in the tree.
  2. Every figure has all of its artifacts. Editing the spec and rerunning without
     --export leaves the `.drawio` newer than the `.svg` and `.png` the documents embed,
     and the documents keep showing the stale picture.
  3. No Japanese character survives in an English artifact. This is the one failure the
     build's own residue gate cannot catch retroactively: a label added to LABELS
     incorrectly, or a `.drawio` hand-edited after generation, shows up here.

What it cannot check: whether the `.svg` was exported from the `.drawio` beside it. Git
stores no timestamps and there is no renderer available, so a `.drawio` change committed
without a re-export passes item 2 as long as the old files exist. Look at the PNG.

Exit codes: 0 the artifacts are consistent, 1 something drifted.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET  # nosec B405  # noqa: S405  parses our own output
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGRAM_DIR = ROOT / "docs" / "_assets" / "diagrams"
IMAGE_DIR = ROOT / "docs" / "_assets" / "images"
PNG_DIR = IMAGE_DIR / "png"

sys.path.insert(0, str(ROOT / "tools"))

# 図の一覧は build_diagrams が持っている。**ここに書き写すと、図を追加した人が
# この検査に登録し忘れ、成果物が 1 つも無くても「OK」が出る。** 実際に 2 図を追加した
# 直後の実行が「3 figures」を返していた。import は AWS アイコンパッケージも draw.io も
# 要らない（アイコンの解決は書き出し時）。
from build_diagrams import DIAGRAMS  # noqa: E402

FIGURES = tuple(diagram.name for diagram in DIAGRAMS)

SKIP_DIR_PARTS = {".venv", "node_modules", "__pycache__", ".git", ".private"}
ICON_LIBRARY = re.compile(r"^(Arch_|Res_|Icon-package)")
# U+203B (※) is outside every CJK block and would otherwise pass unnoticed. U+3000-303F
# covers 、。「」 for the same reason.
CJK = re.compile(r"[\u203b\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]")


def committed_icon_library() -> list[str]:
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or SKIP_DIR_PARTS & set(path.parts):
            continue
        if ICON_LIBRARY.match(path.name):
            found.append(path.relative_to(ROOT).as_posix())
    return sorted(found)


def expected_artifacts(figure: str) -> list[Path]:
    """Eight per figure: four sources, two SVG, four PNG… minus the dark SVG.

    There is no dark SVG on purpose. The SVG export carries both themes as CSS
    `light-dark()` pairs and the viewer picks, so the light file serves a dark-mode reader
    too. A PNG cannot do that, which is the only reason the dark rasters exist.
    """
    return [
        DIAGRAM_DIR / f"{figure}.drawio",
        DIAGRAM_DIR / f"{figure}-en.drawio",
        DIAGRAM_DIR / f"{figure}-dark.drawio",
        DIAGRAM_DIR / f"{figure}-en-dark.drawio",
        IMAGE_DIR / f"{figure}.svg",
        IMAGE_DIR / f"{figure}-en.svg",
        PNG_DIR / f"{figure}@2x.png",
        PNG_DIR / f"{figure}-en@2x.png",
        PNG_DIR / f"{figure}-dark@2x.png",
        PNG_DIR / f"{figure}-en-dark@2x.png",
    ]


def main() -> int:
    problems: list[str] = []

    for relative in committed_icon_library():
        problems.append(
            f"{relative}: icon-library file committed. The AWS icon package is licensed "
            "for use in diagrams, not for redistribution; keep it outside the repo."
        )

    checked = 0
    for figure in FIGURES:
        for path in expected_artifacts(figure):
            relative = path.relative_to(ROOT).as_posix()
            if not path.is_file():
                problems.append(f"{relative}: missing. Rebuild with --write --export.")
                continue
            if path.stat().st_size == 0:
                problems.append(f"{relative}: empty.")
                continue
            checked += 1

            if path.suffix == ".drawio":
                try:
                    ET.parse(path)  # nosec B314  # noqa: S314  our own generated file
                except ET.ParseError as error:
                    problems.append(f"{relative}: not well-formed XML ({error})")

            if "-en" in path.stem and path.suffix in (".drawio", ".svg"):
                residue = sorted(set(CJK.findall(path.read_text(encoding="utf-8"))))
                if residue:
                    problems.append(
                        f"{relative}: {len(residue)} Japanese character(s) remain in an "
                        f"English artifact: {''.join(residue[:20])}"
                    )

    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(f"diagram assets: {len(problems)} problem(s)", file=sys.stderr)
        return 1

    print(f"diagram assets: OK ({len(FIGURES)} figures, {checked} artifacts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
