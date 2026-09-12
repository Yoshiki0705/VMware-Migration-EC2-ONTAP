#!/usr/bin/env python3
"""AWS サポートケースの状態と応答ログを Support API から生成する。

この台帳を人が書いていた時期に、返信のドラフトを書いた事実を「送信済み」として記録し、
実際には一度も送信されていないケースが 1 件生まれた。ドラフトの存在は送信の証拠ではない。
そのため状態の出所を AWS 側の通信履歴だけに寄せ、ローカルの表は生成物にしている。

  python3 scripts/sync_support_case_status.py            # 生成する
  python3 scripts/sync_support_case_status.py --check     # 差分があれば exit 1

生成先はいずれも .private/（Git 追跡対象外）。ケース ID と回答本文は公開物に出さない。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / ".private" / "aws-support-cases"
LEDGER = CASES_DIR / "_created.tsv"
STATUS = CASES_DIR / "_status.md"
REPLIES_DIR = CASES_DIR / "replies"

# サポートの窓口が自動送信するアンケート。返信の要否の判定からは除く。
SURVEY_MARKER = "questionnaireId=Support-HMD"
AWS_SUBMITTER = "Amazon Web Services"


@dataclass(frozen=True)
class Comm:
    by: str
    at: str
    body: str

    @property
    def from_aws(self) -> bool:
        return AWS_SUBMITTER in self.by

    @property
    def is_survey(self) -> bool:
        return SURVEY_MARKER in self.body


@dataclass
class Case:
    display_id: str
    slug: str
    subject: str
    status: str = "不明"
    comms: list[Comm] | None = None

    @property
    def last_ours(self) -> str:
        return max((c.at for c in self.comms or [] if not c.from_aws), default="")

    @property
    def last_aws_substantive(self) -> str:
        return max(
            (c.at for c in self.comms or [] if c.from_aws and not c.is_survey),
            default="",
        )

    @property
    def awaiting_our_reply(self) -> bool:
        """AWS の実質回答がこちらの最終送信より新しいか。"""
        return bool(self.last_aws_substantive) and self.last_aws_substantive > self.last_ours


def read_ledger() -> list[Case]:
    if not LEDGER.exists():
        sys.exit(f"台帳が見つかりません: {LEDGER}")
    cases = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            sys.exit(f"台帳の形式が不正です（3 列必要）: {line!r}")
        display_id, filename, subject = parts[0].strip(), parts[1].strip(), parts[2].strip()
        cases.append(Case(display_id=display_id, slug=Path(filename).stem, subject=subject))
    if not cases:
        sys.exit(f"台帳に 1 件もありません: {LEDGER}")
    return cases


def fetch(cases: list[Case]) -> None:
    try:
        import boto3
    except ImportError:
        sys.exit("boto3 が必要です: pip install -r requirements.txt")

    client = boto3.client("support", region_name="us-east-1")
    wanted = {c.display_id for c in cases}
    by_display = {c.display_id: c for c in cases}
    case_ids: dict[str, str] = {}

    for resolved in (False, True):
        paginator = client.get_paginator("describe_cases")
        pages = paginator.paginate(
            language="ja",
            includeResolvedCases=resolved,
            includeCommunications=False,
        )
        for page in pages:
            for raw in page.get("cases", []):
                if raw["displayId"] in wanted:
                    case = by_display[raw["displayId"]]
                    # open 側を先に見るので、resolved 側で上書きしない
                    if raw["displayId"] not in case_ids:
                        case.status = raw["status"]
                        case_ids[raw["displayId"]] = raw["caseId"]

    missing = wanted - case_ids.keys()
    if missing:
        print(f"警告: AWS 側で見つからないケース: {sorted(missing)}", file=sys.stderr)

    for display_id, case_id in case_ids.items():
        comms: list[Comm] = []
        paginator = client.get_paginator("describe_communications")
        for page in paginator.paginate(caseId=case_id):
            for raw in page.get("communications", []):
                comms.append(Comm(by=raw["submittedBy"], at=raw["timeCreated"], body=raw["body"]))
        by_display[display_id].comms = sorted(comms, key=lambda c: c.at)


def render_status(cases: list[Case]) -> str:
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "# AWS サポートケースの状態",
        "",
        "<!-- 生成物。手で編集しない。scripts/sync_support_case_status.py で再生成する。 -->",
        "",
        f"**生成 {stamp}** — 出所は Support API の通信履歴。ドラフトの有無は状態に反映しない。",
        "",
        "| # | 件名の要旨 | 状態 | 最終送信 | 要返信 |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        who = "—"
        stamp_last = "—"
        latest = max((c for c in case.comms or []), key=lambda c: c.at, default=None)
        if latest is not None:
            who = "AWS" if latest.from_aws else "当方"
            if latest.from_aws and latest.is_survey:
                who = "AWS（アンケート）"
            stamp_last = latest.at[:10]
        flag = "**要**" if case.awaiting_our_reply else "—"
        subject = case.subject.replace("|", "\\|")
        lines.append(
            f"| {case.slug.split('-')[0]} | {subject} | {case.status} "
            f"| {who} {stamp_last} | {flag} |"
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
    for comm in case.comms or []:
        who = "AWS" if comm.from_aws else "自分"
        if comm.from_aws and comm.is_survey:
            lines += [f"## [{who}] {comm.at} — アンケート（本文は省略）", ""]
            continue
        lines += [f"## [{who}] {comm.at}", "", comm.body.replace("\r\n", "\n").rstrip(), ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="生成結果が現在のファイルと一致するかだけ確認し、差分があれば exit 1",
    )
    args = parser.parse_args()

    cases = read_ledger()
    fetch(cases)

    outputs: dict[Path, str] = {STATUS: render_status(cases)}
    for case in cases:
        if case.comms:
            outputs[REPLIES_DIR / f"{case.slug}.reply.md"] = render_thread(case)

    if args.check:
        stale = [p for p, text in outputs.items() if not p.exists() or p.read_text() != text]
        if stale:
            for path in stale:
                print(f"差分: {path.relative_to(CASES_DIR.parent.parent)}", file=sys.stderr)
            return 1
        print(f"一致: {len(outputs)} ファイル")
        return 0

    REPLIES_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text)
    awaiting = [c for c in cases if c.awaiting_our_reply]
    print(f"生成しました: {len(outputs)} ファイル / 要返信 {len(awaiting)} 件")
    for case in awaiting:
        print(f"  要返信 {case.slug}: {case.subject[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
