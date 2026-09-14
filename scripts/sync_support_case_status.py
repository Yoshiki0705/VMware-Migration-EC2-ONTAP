#!/usr/bin/env python3
"""AWS サポートケースの状態と応答ログを Support API から生成する。

この台帳を人が書いていた時期に、返信のドラフトを書いた事実を「送信済み」として記録し、
実際には一度も送信されていないケースが 1 件生まれた。ドラフトの存在は送信の証拠ではない。
そのため状態の出所を AWS 側の通信履歴だけに寄せ、ローカルの表は生成物にしている。

  python3 scripts/sync_support_case_status.py            # 生成する
  python3 scripts/sync_support_case_status.py --check     # 差分があれば exit 1

生成先はいずれも .private/（Git 追跡対象外）。ケース ID と回答本文は公開物に出さない。

**この 2 度目の実装は、1 度目が消えたあとに書いた。** `_status.md` は「このスクリプトで
再生成する」と宣言したまま残り、スクリプトは追跡されていなかったので、`__pycache__` の
`.pyc` だけが残って再生成できない状態が 2 日続いた。**生成物が指す生成器は、追跡されて
いなければ次のセッションに存在しない。**
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / ".private" / "aws-support-cases"
LEDGER = CASES_DIR / "_created.tsv"
STATUS = CASES_DIR / "_status.md"
REPLIES_DIR = CASES_DIR / "replies"
DRAFTS_DIR = CASES_DIR / "drafts"

# アンケートの自動メールに必ず入るリンクのクエリ。**これを AWS の回答として数えると
# 全ケースが恒久的に「要返信」になる。** 実際に起きた誤判定なので本文で判定する。
SURVEY_MARKER = "questionnaireId=Support-HMD"
AWS_SUBMITTER = "Amazon Web Services"


@dataclass
class Comm:
    """1 通。**送信者と、それがアンケートかどうかだけが判定に効く。**"""

    from_aws: bool
    is_survey: bool
    at: str
    body: str


@dataclass
class Case:
    display_id: str
    slug: str
    subject: str
    status: str = ""
    comms: list[Comm] = field(default_factory=list)

    @property
    def awaiting_our_reply(self) -> bool:
        """AWS の**実質的な**回答が、当方の最終送信より新しいか。

        アンケートは回答ではない。当方が送っていないケース（申告しただけ）も、
        AWS からの実質回答が無ければ待たせていない。**両方向を誤らないことが要件で、
        「要返信を検出できる」だけの判定は使えない。**
        """
        answers = [c for c in self.comms if c.from_aws and not c.is_survey]
        ours = [c for c in self.comms if not c.from_aws]
        if not answers or not ours:
            return False
        return max(c.at for c in answers) > max(c.at for c in ours)


def read_ledger() -> list[Case]:
    if not LEDGER.exists():
        sys.exit(f"台帳が見つかりません: {LEDGER}")
    cases: list[Case] = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            sys.exit(f"台帳の形式が不正です（3 列必要）: {line}")
        display_id, request_file, subject = parts
        cases.append(Case(display_id.strip(), Path(request_file.strip()).stem, subject.strip()))
    if not cases:
        sys.exit(f"台帳に 1 件もありません: {LEDGER}")
    return cases


def fetch(cases: list[Case]) -> list[Case]:
    """状態と通信履歴を Support API から入れる。

    台帳が持つのは displayId で、`describe_communications` が要求するのは caseId なので、
    `describe_cases` を 1 度引いて対応を作る。**台帳にあって AWS に無いケースは警告に出す** —
    黙って 0 件として扱うと、消えたケースが「通信なし」に化ける。
    """
    try:
        import boto3
    except ImportError:
        sys.exit("boto3 が必要です: pip install -r requirements.txt")

    client = boto3.client("support", region_name="us-east-1")
    known: dict[str, tuple[str, str]] = {}
    for page in client.get_paginator("describe_cases").paginate(
        includeResolvedCases=True, language="ja"
    ):
        for case in page["cases"]:
            known[case["displayId"]] = (case["caseId"], case["status"])

    missing = [c.display_id for c in cases if c.display_id not in known]
    if missing:
        print(f"警告: AWS 側で見つからないケース: {', '.join(missing)}", file=sys.stderr)

    for case in cases:
        if case.display_id not in known:
            continue
        case_id, case.status = known[case.display_id]
        comms = client.describe_communications(caseId=case_id, maxResults=100)["communications"]
        case.comms = sorted(
            (
                Comm(
                    from_aws=AWS_SUBMITTER in m["submittedBy"],
                    is_survey=SURVEY_MARKER in m["body"],
                    at=m["timeCreated"],
                    body=m["body"],
                )
                for m in comms
            ),
            key=lambda c: c.at,
        )
    return cases


def dense(text: str) -> str:
    """空白を全部落とした比較用の形。

    ドラフトは 100 桁で折り返して書き、送信欄は折り返しを保たない。**改行位置が違うだけの
    同一本文を別物として扱わないため**に、比較の前に空白を消す。
    """
    return "".join(text.split())


def sent_drafts(cases: list[Case]) -> list[tuple[Path, str]]:
    """`drafts/` に残っているのに、本文が既に送信済みのドラフト。

    **このスクリプトが存在する理由の裏返し。** 「ドラフトの存在は送信の証拠ではない」ので
    状態は通信履歴から作るが、逆に**送信後もドラフトが残っていると、見出しの状態表記
    （送信前レビュー待ち など）が実態と食い違ったまま残る。** 実際に 1 件そうなっていた。
    """
    found: list[tuple[Path, str]] = []
    if not DRAFTS_DIR.exists():
        return found
    by_slug = {case.slug: case for case in cases}
    for draft in sorted(DRAFTS_DIR.glob("*.md")):
        case = by_slug.get(draft.name.split(".")[0])
        if case is None:
            continue
        body_lines = [
            line
            for line in draft.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ">", "-", "*", "|", "**"))
        ]
        # 行単位で 24 字を探すと、短い行で書かれたドラフトを取り逃す。**本文を 1 本に
        # 詰めてから先頭を取る**ので、折り返しの位置と 1 行の長さのどちらにも依存しない。
        probe = dense(" ".join(body_lines))[:40]
        if len(probe) < 24:
            continue
        for comm in case.comms:
            if not comm.from_aws and probe in dense(comm.body):
                found.append((draft, comm.at))
                break
    return found


def render_status(cases: list[Case]) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "# AWS サポートケースの状態",
        "",
        "<!-- 生成物。手で編集しない。scripts/sync_support_case_status.py で再生成する。 -->",
        "",
        f"**生成 {generated}** — 出所は Support API の通信履歴。ドラフトの有無は状態に反映しない。",
        "",
        "| # | 件名の要旨 | 状態 | 最終送信 | 要返信 |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        last = max(case.comms, key=lambda c: c.at) if case.comms else None
        if last is None:
            sender, at = "—", "-"
        else:
            sender = "AWS（アンケート）" if last.is_survey else ("AWS" if last.from_aws else "当方")
            at = last.at[:10]
        number = case.slug.split("-")[0]
        subject = case.subject.replace("|", "\\|")
        need = "**要**" if case.awaiting_our_reply else "—"
        lines.append(
            f"| {number} | {subject} | {case.status or '-'} | {sender} {at} | {need} |".replace(
                "| — - |", "| — |"
            )
        )
    lines += [
        "",
        "「要返信」は、アンケート以外の AWS 最終回答がこちらの最終送信より新しいことを指す。",
        "AWS がクローズを宣言している場合は返信すると再オープンになるため、情報が動くときだけ返す。",
        "",
    ]
    return "\n".join(lines)


def render_thread(case: Case) -> str:
    lines = [
        f"# AWS Support 応答ログ — {case.slug}",
        "",
        "<!-- 生成物。手で編集しない。scripts/sync_support_case_status.py で再生成する。 -->",
        "",
        "**AWS の回答内容は AWS の秘密情報として扱う。公開物の根拠には使わない。**",
        "公開できるのは、回答が指し示した公開ドキュメントの URL と、その本文を自分で読んで確認した事実だけ。",
        "",
        f"件名: {case.subject}",
        "",
    ]
    for comm in case.comms:
        who = "AWS" if comm.from_aws else "自分"
        if comm.is_survey:
            lines += [f"## [{who}] {comm.at} — アンケート（本文は省略）", ""]
            continue
        lines += [f"## [{who}] {comm.at}", "", comm.body.replace("\r\n", "\n").rstrip(), ""]
    # 末尾を 1 行空ける。**既存の応答ログと byte 一致させるため** — 一致しないと `--check` が
    # 状態の変化と書式の差を区別できず、毎回 13 ファイルの差分を報告する。
    return "\n".join([*lines, ""])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="生成結果が現在のファイルと一致するかだけ確認し、差分があれば exit 1",
    )
    args = parser.parse_args()

    cases = fetch(read_ledger())
    rendered = {STATUS: render_status(cases)}
    for case in cases:
        rendered[REPLIES_DIR / f"{case.slug}.reply.md"] = render_thread(case)

    if args.check:
        drift = [
            p
            for p, body in rendered.items()
            if not p.exists() or p.read_text(encoding="utf-8") != body
        ]
        for path in drift:
            print(f"差分: {path.relative_to(CASES_DIR.parent)}")
        if drift:
            return 1
        print(f"一致: {len(rendered)} ファイル")
        return 0

    REPLIES_DIR.mkdir(parents=True, exist_ok=True)
    for path, body in rendered.items():
        path.write_text(body, encoding="utf-8")
    awaiting = [c for c in cases if c.awaiting_our_reply]
    print(f"生成しました: {len(rendered)} ファイル / 要返信 {len(awaiting)} 件")
    for case in awaiting:
        print(f"  要返信 {case.slug}: {case.subject[:52]}")
    for draft, at in sent_drafts(cases):
        print(
            f"警告: 送信済みのドラフトが残っています（{at[:10]} に送信）: "
            f"{draft.relative_to(CASES_DIR.parent)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
