#!/usr/bin/env python3
"""散文中の GitHub リポジトリ名が、いまの名前であることを検査する。

改名は普通のことである。生き延びられないのは、**旧名が引き続き解決する**ことだ。
2 つの文書が同じリポジトリを別の名前で書いていても、どちらも壊れて見えない。
リンクチェッカーは全 URL を到達可能と報告し、何も上がらない。

このリポジトリ自身が旧名 `vmware-migration-ec2-ontap` として姉妹リポジトリから
リンクされ続けた側だった。Playbook へ逆方向のリンクを張るなら、同じ危険を
こちらが負う。それを報告する仕組みがここにないので置く。

移植元との違いが 3 つある。いずれも意図的である。

1. **HTML のリダイレクトではなく API の `full_name` を見る。**
   GitHub はリポジトリ名を大文字小文字を区別せずに解決し、要求された綴りのまま
   200 で返す。したがって最終 URL の比較では**大小文字のみの改名を検出できない**。
   このリポジトリの改名がまさにそれで、移植元の初版は沈黙した。

2. **コードフェンスの中も走査する。**
   引用の検査ではフェンス内は例示なので除外する。名前の検査では逆で、フェンス内の
   `git clone` URL は読者が実際に実行するので、旧名が最も害を持つ場所である。

3. **自分のリポジトリを除外しない。**
   除外すると、次にこのリポジトリが改名されたときバッジと clone URL が黙って腐る。
   全件を解決すれば、旧名で自分を指している状態もここで上がる。

失敗の切り分け:

    旧名が見つかった            → exit 1（検出）
    旧名はないが解決できない名前 → exit 2（判定不能）

レート制限や障害を「旧名」として報告するゲートは無視されるようになる。判定できな
かったことは、検出できなかったことと別に報告する。

    python3 tools/check_repo_names.py --selftest   # 抽出と比較の能力（ネットワーク不要）
    python3 tools/check_repo_names.py              # リポジトリ全体（ネットワーク必要）

未認証の API は 1 時間 60 回で、この file を触りながら試すと足りない。
`GITHUB_TOKEN` があれば読み、5,000 回に上がる。追加の permission は要らない。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = "Yoshiki0705"

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

# 名前のセグメントは `/` を含まない。`/blob/...` や `/actions/...` は入らない。
REPO_REF = re.compile(rf"https://github\.com/{OWNER}/(?P<repo>[A-Za-z0-9._-]+)")

API = "https://api.github.com/repos/{owner}/{repo}"


def normalize(repo: str) -> str:
    """URL から取れた綴りを、API に渡せるリポジトリ名にする。

    clone URL は `.git` で終わる。文末のリンクは `.` や `)` の直前で切れる。
    どちらも剥がさないと API が 404 を返し、正しい名前が「解決できない」として
    上がる。判定不能の報告は、本当に判定できなかったときのために取っておく。
    """
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return repo.rstrip(".")


def references(text: str) -> set[str]:
    # 剥がした結果が空になる綴り（`.` だけ、`..` など）は名前ではない。残すと API に
    # 空のセグメントを投げ、判定不能として報告することになる。
    found = {normalize(m.group("repo")) for m in REPO_REF.finditer(text)}
    return {repo for repo in found if repo}


def prose_files() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.md") if not any(part in SKIP for part in p.relative_to(ROOT).parts)
    )


def collect() -> dict[str, list[str]]:
    """リポジトリ名 → それを書いているファイルの一覧。"""
    seen: dict[str, list[str]] = {}
    for path in prose_files():
        rel = path.relative_to(ROOT).as_posix()
        for repo in sorted(references(path.read_text(encoding="utf-8"))):
            seen.setdefault(repo, [])
            if rel not in seen[repo]:
                seen[repo].append(rel)
    return seen


def canonical_name(repo: str) -> tuple[str | None, str | None]:
    """(現在の名前, 判定できなかった理由) を返す。両方が埋まることはない。"""
    headers = {
        "User-Agent": "repo-name-check",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API.format(owner=OWNER, repo=repo), headers=headers)
    try:
        # B310 は urlopen が file: などのスキームを開きうることへの警告。ここで組む URL は
        # 常に https の定数で、差し替わるのは名前のセグメントだけである。名前は
        # `[A-Za-z0-9._-]+` にしか一致しないので `:` も `/` も入らず、スキームを持ち込めない。
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return None, f"cannot resolve ({exc})"
    full_name = str(payload.get("full_name", ""))
    if "/" not in full_name:
        return None, "cannot resolve (the API response carried no full_name)"
    return full_name.rsplit("/", 1)[-1], None


CASES: list[tuple[str, set[str]]] = [
    ("https://github.com/Yoshiki0705/Repo-One", {"Repo-One"}),
    # clone URL の `.git`、文末の `.`、`)` の直前。剥がさないと 404 になる。
    ("git clone https://github.com/Yoshiki0705/Repo-One.git", {"Repo-One"}),
    ("see https://github.com/Yoshiki0705/Repo-One.", {"Repo-One"}),
    ("[x](https://github.com/Yoshiki0705/Repo-One)", {"Repo-One"}),
    # blob / actions のパスは名前に混ぜない。
    ("https://github.com/Yoshiki0705/Repo-One/blob/main/docs/a.md", {"Repo-One"}),
    (
        "https://github.com/Yoshiki0705/Repo-One/actions/workflows/ci.yml/badge.svg",
        {"Repo-One"},
    ),
    # コードフェンスの中も拾う。clone URL は読者が実行するので旧名が最も効く場所。
    ("```bash\ngit clone https://github.com/Yoshiki0705/Repo-One.git\n```", {"Repo-One"}),
    # 他の owner は対象外。
    ("https://github.com/other-owner/Repo-One", set()),
    ("no repository reference here", set()),
]


def selftest() -> int:
    bad: list[str] = []
    for text, want in CASES:
        got = references(text)
        if got != want:
            bad.append(f"expected {sorted(want)}, got {sorted(got)}: {text!r}")
    # 比較は大文字小文字を区別する。ここが区別しなくなると、この検査が書かれた
    # 理由そのもの（大小文字のみの改名）に沈黙する。
    if "vmware-migration-ec2-ontap".lower() == "VMware-Migration-EC2-ONTAP":
        bad.append("case-sensitive comparison lost")
    if "VMware-Migration-EC2-ONTAP" == "vmware-migration-ec2-ontap":
        bad.append("case-only difference read as equal")
    for line in bad:
        print(f"selftest FAIL: {line}", file=sys.stderr)
    if bad:
        return 1
    print(f"selftest: {len(CASES) + 2} case(s) passed")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    seen = collect()
    if not seen:
        print("repo names: no GitHub repository reference found")
        return 0

    stale: list[str] = []
    undetermined: list[str] = []
    for repo, files in sorted(seen.items()):
        canonical, reason = canonical_name(repo)
        listed = ", ".join(files[:4]) + (" …" if len(files) > 4 else "")
        if reason is not None:
            undetermined.append(f"{repo}: {reason}. Named in: {listed}")
            continue
        if canonical != repo:
            stale.append(
                f"{repo} is not the current name; it is {canonical}. "
                f"The old name still resolves, so nothing else reports it. "
                f"Update: {listed}"
            )

    if stale:
        print(f"stale repository name(s) found ({len(stale)}):")
        for line in stale:
            print(f"  {line}")
    if undetermined:
        # 判定できなかったことは、検出できなかったことと別に出す。
        print(f"could not judge ({len(undetermined)}):", file=sys.stderr)
        for line in undetermined:
            print(f"  {line}", file=sys.stderr)
    if stale:
        return 1
    if undetermined:
        print(
            f"\n{len(seen) - len(undetermined)} name(s) checked, "
            f"{len(undetermined)} unresolved. No stale name found among those judged.",
            file=sys.stderr,
        )
        return 2
    print(f"repo names: {len(seen)} name(s) are current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
