"""返信の要否の判定を、両方向で確かめる。

この判定が生まれた理由は、ドラフトを書いた事実が「送信済み」として台帳に残り、AWS の回答に
8 日間応答しないケースが生まれたことである。したがって確かめるべきは「要返信を検出できる」
だけでなく「返信済みを要返信と誤検出しない」ことでもある。片方だけ通る判定は使えない。

アンケートの自動メールを AWS の回答として数えてしまうと、全ケースが恒久的に要返信になる。
それも実際に起きた誤判定なので、明示的に 1 件置く。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_support_case_status as sync  # noqa: E402

SURVEY_BODY = (
    "お客様の問題解決にお役に立てたでしょうか: "
    "https://console.aws.amazon.com/support/feedback?eventId=1&questionnaireId=Support-HMD-Yes"
)


def case(*comms: sync.Comm) -> sync.Case:
    return sync.Case(display_id="1", slug="09-x", subject="件名", comms=list(comms))


def ours(at: str) -> sync.Comm:
    return sync.Comm(by="someone (IAM) <someone@example.com>", at=at, body="こちらの返信")


def aws(at: str, body: str = "回答です") -> sync.Comm:
    return sync.Comm(by="Amazon Web Services", at=at, body=body)


def test_aws_answered_after_us_needs_a_reply() -> None:
    assert case(ours("2026-09-04T00:00:00Z"), aws("2026-09-10T00:00:00Z")).awaiting_our_reply


def test_our_reply_after_the_answer_clears_it() -> None:
    subject = case(
        ours("2026-09-04T00:00:00Z"),
        aws("2026-09-10T00:00:00Z"),
        ours("2026-09-12T00:00:00Z"),
    )
    assert not subject.awaiting_our_reply


def test_survey_after_our_reply_is_not_an_answer() -> None:
    """アンケートを回答と数えると、返信済みのケースが永久に要返信になる。"""
    subject = case(
        ours("2026-09-04T00:00:00Z"),
        aws("2026-09-10T00:00:00Z"),
        ours("2026-09-12T00:00:00Z"),
        aws("2026-09-12T01:00:00Z", SURVEY_BODY),
    )
    assert not subject.awaiting_our_reply


def test_only_our_filing_so_far_is_not_awaiting_us() -> None:
    """起票しただけで AWS が何も返していない状態は、こちらの手番ではない。"""
    assert not case(ours("2026-09-04T00:00:00Z")).awaiting_our_reply


def test_draft_on_disk_does_not_affect_the_verdict() -> None:
    """判定に使う入力は通信履歴だけである。ローカルのファイルは一切見ない。"""
    subject = case(ours("2026-09-04T00:00:00Z"), aws("2026-09-10T00:00:00Z"))
    assert subject.awaiting_our_reply
    assert (REPO_ROOT / "scripts" / "sync_support_case_status.py").read_text().count("drafts") == 0


def test_ledger_rows_need_three_columns(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "_created.tsv"
    bad.write_text("178853231400330\t01-snapshot-fallback.txt\n")
    monkeypatch.setattr(sync, "LEDGER", bad)
    try:
        sync.read_ledger()
    except SystemExit as exc:
        assert "3 列" in str(exc)
    else:
        raise AssertionError("2 列の行を受け入れてしまった")
