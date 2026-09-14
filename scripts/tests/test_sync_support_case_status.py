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
    "問題が解決したかどうかお知らせください: "
    "https://console.aws.amazon.com/support/feedback?eventId=1&questionnaireId=Support-HMD-Yes"
)


def case(*comms: sync.Comm) -> sync.Case:
    return sync.Case("178800000000000", "07-finalize-capacity", "件名", "resolved", list(comms))


def ours(at: str) -> sync.Comm:
    return sync.Comm(from_aws=False, is_survey=False, at=at, body="当方の送信")


def aws(at: str, body: str = "AWS の回答") -> sync.Comm:
    return sync.Comm(from_aws=True, is_survey=sync.SURVEY_MARKER in body, at=at, body=body)


def test_aws_answered_after_us_needs_a_reply() -> None:
    assert case(ours("2026-09-12T00:00:00Z"), aws("2026-09-13T01:00:00Z")).awaiting_our_reply


def test_our_reply_after_the_answer_clears_it() -> None:
    """**この方向を落とすと、返信済みが恒久的に要返信として残る。**"""
    assert not case(aws("2026-09-11T07:00:00Z"), ours("2026-09-12T00:08:00Z")).awaiting_our_reply


def test_survey_after_our_reply_is_not_an_answer() -> None:
    """アンケートは AWS からの通信だが回答ではない。数えると全件が要返信になる。"""
    subject = case(
        aws("2026-09-11T07:00:00Z"),
        ours("2026-09-12T00:08:00Z"),
        aws("2026-09-12T15:40:00Z", SURVEY_BODY),
    )
    assert not subject.awaiting_our_reply
    last = max(subject.comms, key=lambda c: c.at)
    assert last.is_survey, "アンケートの判定が本文から取れていない"


def test_only_our_filing_so_far_is_not_awaiting_us() -> None:
    """申告しただけでまだ回答が無いケースを、こちらが待たせている扱いにしない。"""
    assert not case(ours("2026-09-04T14:40:00Z")).awaiting_our_reply


def test_draft_on_disk_does_not_affect_the_verdict() -> None:
    """**ドラフトの存在は送信の証拠ではない。** この混同がこの生成器を作った理由である。

    判定は通信履歴だけを見る。ディスク上のドラフトを見る経路が無いことを、`Case` が
    ファイルシステムに触れないことで示す。
    """
    subject = case(aws("2026-09-13T01:00:00Z"), ours("2026-09-12T00:00:00Z"))
    assert subject.awaiting_our_reply
    assert not any(isinstance(getattr(subject, name, None), Path) for name in vars(subject)), (
        "Case がパスを持つと、ドラフトの有無が判定に入りうる"
    )


def test_ledger_rows_need_three_columns() -> None:
    """列が欠けた台帳を黙って読み飛ばすと、ケースが 1 件消えたまま表が生成される。"""
    import pytest

    original = sync.LEDGER
    try:
        broken = REPO_ROOT / "scripts" / "tests" / "_broken_ledger.tsv"
        broken.write_text("178800000000000\t07-finalize-capacity.txt\n", encoding="utf-8")
        sync.LEDGER = broken
        with pytest.raises(SystemExit) as raised:
            sync.read_ledger()
        assert "3 列" in str(raised.value)
    finally:
        sync.LEDGER = original
        broken.unlink(missing_ok=True)


def test_a_draft_whose_body_was_already_sent_is_reported(tmp_path: Path) -> None:
    """送信後に残ったドラフトを見つける。**見出しの状態表記が実態と食い違ったまま残る形。**

    実際に 1 件そうなっていた。本文は 2026-09-12 に送信済みで、ドラフトの見出しは
    「送信前レビュー待ち」「pending-customer-action」のままだった。
    """
    sent = "ご確認と再現の検証をいただき、ありがとうございました。3 点お返しします。"
    subject = case(
        ours("2026-09-04T14:40:00Z"),
        aws("2026-09-11T07:23:00Z"),
        sync.Comm(from_aws=False, is_survey=False, at="2026-09-12T00:08:00Z", body=sent),
    )
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    # ドラフトは折り返して書き、送信欄は折り返しを保たない。**改行位置だけが違う**状態を
    # 別物と扱わないことも、ここで確かめる。
    (drafts / "07-finalize-capacity.reply-draft.md").write_text(
        "# 返信ドラフト（送信前レビュー待ち）\n\n**ケース**: pending-customer-action\n\n"
        "ご確認と再現の検証をいただき、\nありがとうございました。3 点お返しします。\n",
        encoding="utf-8",
    )
    original = sync.DRAFTS_DIR
    try:
        sync.DRAFTS_DIR = drafts
        found = sync.sent_drafts([subject])
    finally:
        sync.DRAFTS_DIR = original
    assert len(found) == 1
    assert found[0][1].startswith("2026-09-12")


def test_a_draft_that_was_never_sent_is_not_reported(tmp_path: Path) -> None:
    """**この方向を落とすと、レビュー待ちのドラフトが毎回警告になり、警告が読まれなくなる。**"""
    subject = case(ours("2026-09-04T14:40:00Z"), aws("2026-09-11T07:23:00Z"))
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "07-finalize-capacity.reply-draft.md").write_text(
        "# 返信ドラフト（送信前レビュー待ち）\n\nまだ誰にも送っていない本文がここにあります。\n",
        encoding="utf-8",
    )
    original = sync.DRAFTS_DIR
    try:
        sync.DRAFTS_DIR = drafts
        assert sync.sent_drafts([subject]) == []
    finally:
        sync.DRAFTS_DIR = original
