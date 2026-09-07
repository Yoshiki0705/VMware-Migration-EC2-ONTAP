#!/usr/bin/env python3
"""ラベルに職種名とレンズ語が同居していないことを検査する。

`> **Storage Specialist レンズ**:` や `#### 3c. …（Storage Specialist 観点）` のような
ラベルは、**その職種の人がレビューした**と読める。実際には AI が文書を読んで書いた所見
であることが多く、読者にとっては出所の誤認になる。所見そのものは有効なので、変えるのは
ラベルだけでよい。

**語だけを禁止しても効かない。** 「観点」「視点」は日常語で、「セキュリティの観点から」に
発火するルールは allow マーカーを付けられて終わり、以後は何も守らない。そこで
**職種トークンとレンズ語が同じラベルに同居していること**を条件にする。

| 入力 | 判定 |
|---|---|
| `## 前提の整理（Storage Specialist 観点）` | 検出 |
| `> **AppSec レンズ**: x` | 検出 |
| `## コストの観点から見た選択` | 通過 |
| `> **Cost note**: セキュリティの観点からも確認します。` | 通過 |

ラベルとみなすのは 3 つの形だけである。散文の中の「〜の観点から」は対象にしない。

    見出し行の本文        `## …`
    引用の先頭の太字      `> **…**`
    行頭の太字ラベル      `**…**:`

**コードフェンスの中は見ない。** これは `check_repo_names.py` と逆である。あちらはフェンス
内の clone URL が読者に実行されるので走査する。こちらはフェンス内の例示が禁止形を示すため
の引用であり、published なラベルではない。**同じテキストに 2 つの検査が逆を要求する。**

規約を示すために禁止形をそのまま書く必要がある行は、行末に
`<!-- allow:role-label -->` を付けて除外し、理由を前後の本文に書く。

    python3 tools/check_role_labels.py --selftest   # 検査が落ちる能力の確認
    python3 tools/check_role_labels.py              # リポジトリ全体
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP = {
    ".git",
    "node_modules",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".private",
    ".kiro",
    ".pytest_cache",
    ".ruff_cache",
}

FENCE = re.compile(r"^\s*(?:```|~~~)")
ALLOW = re.compile(r"<!--\s*allow:role-label\s*-->")

# ラベルとみなす 3 つの形。散文は対象にしない。
LABEL_PATTERNS = (
    re.compile(r"^#{1,6}\s+(?P<label>.*?)\s*$"),
    re.compile(r"^>\s*\*\*(?P<label>[^*]+)\*\*"),
    re.compile(r"^\*\*(?P<label>[^*]+)\*\*\s*[:：]"),
)

# 職種を名指すトークン。`SA` のような 2 文字の略語は散文に混ざるので入れない。
# 分野名（FinOps、Reliability/Ops）は職種ではなく話題なので入れない。
ROLE = re.compile(
    r"(?:Specialist|Engineer|Architect|Practitioner|Officer|Analyst|Consultant"
    r"|Administrator|Developer|Manager|Reviewer|AppSec|DevOps Engineer|SRE"
    r"|Pre-Sales|Presales"
    r"|エンジニア|アーキテクト|スペシャリスト|コンサルタント|レビュアー|担当者|責任者|専門家)"
)

LENS = re.compile(r"(?:lens|Lens|レンズ|視点|観点|perspective|Perspective|目線)")


def violations(text: str) -> list[tuple[int, str]]:
    """(行番号, ラベル) を返す。職種トークンとレンズ語が同居するラベルのみ。"""
    hits: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced or ALLOW.search(line):
            continue
        for pattern in LABEL_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            label = match.group("label")
            if ROLE.search(label) and LENS.search(label):
                hits.append((number, label.strip()))
            break
    return hits


CASES: list[tuple[str, bool]] = [
    # --- 検出する: 職種 + レンズ語が同じラベルに同居 ---
    ("## 前提の整理（Storage Specialist 観点）", True),
    ("#### 3c. ストレージ検証（VMware Specialist 観点）", True),
    ("### 設計判断（Security Engineer レンズ）", True),
    ("> **AppSec レンズ**: 権限を絞る", True),
    ("> **Storage Specialist lens**: split needs capacity", True),
    ("**Data Protection Officer の視点**: 保持期間を確認する", True),
    # --- 通過する: レンズ語だけ、または職種だけ ---
    ("## コストの観点から見た選択", False),
    ("> **Cost note**: セキュリティの観点からも確認します。", False),
    ("## Architecture", False),
    ("#### 3d. コスト検証（FinOps 観点）", False),
    ("> **Security note**: 権限を絞る", False),
    # --- 散文はラベルではない ---
    ("Storage Specialist の観点から書かれた記事を読んだ。", False),
    # --- フェンスの中は例示であって published なラベルではない ---
    ("```markdown\n> **Storage Specialist レンズ**: x\n```", False),
    # --- allow マーカーは規約自身が禁止形を示すため ---
    ("## 例（Storage Specialist 観点）<!-- allow:role-label -->", False),
]


def selftest() -> int:
    bad: list[str] = []
    for text, want in CASES:
        if bool(violations(text)) != want:
            bad.append(f"expected flag={want}: {text!r}")
    for line in bad:
        print(f"selftest FAIL: {line}", file=sys.stderr)
    if bad:
        return 1
    print(f"selftest: {len(CASES)} case(s) passed")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    total = 0
    for path in sorted(ROOT.rglob("*.md")):
        if any(part in SKIP for part in path.relative_to(ROOT).parts):
            continue
        hits = violations(path.read_text(encoding="utf-8"))
        if not hits:
            continue
        print(f"\n{path.relative_to(ROOT)}")
        for number, label in hits:
            print(f"  L{number:>4} {label}")
        total += len(hits)

    if total:
        print(
            f"\n{total} 件のラベルが職種名を名乗っています。所見は変えず、"
            "ラベルだけ中立な話題名にしてください（例: Storage note / セキュリティに関する補足）。",
            file=sys.stderr,
        )
        return 1
    print("role labels: no label claims a job title")
    return 0


if __name__ == "__main__":
    sys.exit(main())
