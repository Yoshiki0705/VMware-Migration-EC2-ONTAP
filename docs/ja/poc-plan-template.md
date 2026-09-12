# PoC 実行計画テンプレート: VMware → EC2 + FSx for ONTAP 移行

> パートナー/SI が顧客向けに使用する PoC 計画の雛形

---

## 1. PoC 概要

| 項目 | 記入欄 |
|------|--------|
| 顧客名 | ________________ |
| 実施期間 | ____年__月__日 〜 ____年__月__日 |
| ビジネススポンサー | ________________ |
| 技術リード（顧客側） | ________________ |
| 技術リード（パートナー側） | ________________ |
| 使用ツール | □ Shift Toolkit (Early Preview) □ AWS Transform (GA) □ CMC □ MGN |
| 検証シナリオ | □ 移行 (Migration) □ DR (継続レプリケーション＋復旧) |

### 顧客の最初の質問

> 「VMware の次をどうするか? 今使っているストレージの種類によって最適な移行パスが変わります。」

---

## 2. PoC ゴールと成功指標

### ビジネスゴール（この PoC を行う理由）

| # | ゴール | 記入欄 |
|---|--------|--------|
| G1 | 解決したい課題 | 例: VMware ライセンスコスト増大 / DR 対策 / クラウド移行 |
| G2 | PoC 後の判断 | 例: 本番移行の Go/No-Go 判断材料を得る |
| G3 | 期待する成果 | 例: 移行可能性の確認 + コスト比較レポート |

### 成功指標（PoC の成否判定基準）

| # | 指標 | 目標値 | 測定方法 | Go/No-Go |
|---|------|--------|---------|----------|
| S1 | データディスク変換時間 | ___分以内 / 100GB | Shift Toolkit ログ | Go: 達成 / No-Go: 未達成 |
| S2 | カットオーバー停止時間 | ___分以内 | 時刻記録 | Go: 許容範囲内 |
| S3 | データ整合性 | 100% | sha256sum 比較 | Go: 100% 必須 |
| S4 | 移行後アプリ動作 | 正常応答 | アプリテスト | Go: 全テスト PASS |
| S5 | 月額コスト比較 | 現環境比 ___% 以内 | コスト試算 | Go: 予算内 |

---

## 3. 前提条件チェックリスト

### ツール・シナリオ選択判断

```text
■ シナリオの選択
  移行 (一度きりのリホスト/リプラットフォーム) → ツール選択フローへ
  DR (継続レプリケーション＋復旧)            → SnapMirror ベース構成
       ※ AWS Transform は移行専用。DR のデータ複製は SnapMirror が担う
       ※ 手順: docs/ja/dr-snapmirror-runbook.md

■ 移行ツール選択フロー
Q1: 現在 ONTAP NFS データストアを使用しているか?
    Yes → Q2 へ
    No  → AWS MGN を推奨（本テンプレートのスコープ外）

Q2: データディスクを FSx for ONTAP (iSCSI) に配置したいか?
    Yes → Q3 へ
    No  → AWS MGN を推奨

Q3: 移行の進め方は?
    AWS ネイティブで一気通貫（計画〜コンピュート〜ストレージ）/ ソース混在
        → AWS Transform（VMware 移行は無料・FSx for ONTAP 宛先は 2026-08-30 に GA）
          手順: docs/ja/aws-transform-migration-procedure.md
    ONTAP FlexClone での高速変換・中小規模 / PoC
        → Shift Toolkit (Early Preview) ← 本テンプレート主対象
    100+ VM / ゼロダウンタイム要件
        → Cirrus Migrate Cloud (CMC)
```

### オンプレミス要件

- [ ] VMware vCenter 7.0.3 以降
- [ ] ONTAP 9.14.1 以降
- [ ] VM が NFS データストア上に配置されている
- [ ] Shift Toolkit インストール用 Windows Server を準備可能
- [ ] NetApp Support アカウント保有（Early Preview 有効化用）

### AWS 要件

- [ ] AWS アカウント（適切な IAM 権限）
- [ ] VPN or Direct Connect（オンプレ ↔ AWS 通信）
- [ ] 対象リージョンで FSx for ONTAP が利用可能
- [ ] EC2 Key Pair 作成済み

---

## 4. PoC 対象 VM

| # | VM 名 | OS | vCPU | RAM | OS Disk | Data Disk | 用途 | 優先度 |
|---|-------|-----|------|-----|---------|-----------|------|--------|
| 1 | | | | | | | | High/Med/Low |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

**選定基準:**

- 本番データを含まないテスト用 VM を優先
- Linux + Windows の両方を含める
- データディスクサイズのバリエーション（小/中/大）

---

## 5. 実施スケジュール

| Week | 作業内容 | 担当 | 完了基準 |
|------|---------|------|---------|
| W1 | 環境準備（AWS: VPC/FSx for ONTAP/EC2） | パートナー | CFn デプロイ完了 |
| W1 | 環境準備（オンプレ: Shift Toolkit インストール） | 顧客 | Shift Toolkit GUI 起動確認 |
| W2 | 接続確認（VPN/DX + ポート疎通） | 両者 | ping/telnet 成功 |
| W2 | SnapMirror 設定 + 初期転送 | パートナー | データ同期完了 |
| W3 | 移行テスト実行（VM 1-2台） | 両者 | EC2 起動 + データ確認 |
| W3 | パフォーマンス計測 | パートナー | fio レポート作成 |
| W4 | 結果整理 + コスト比較 + Go/No-Go 判定 | 両者 | 最終レポート提出 |

---

## 6. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| Early Preview の仕様変更 | 手順の再確認が必要 | NetApp との定期連絡、GA 前提の手順は別途整理 |
| OS ディスク AMI 化の追加工程 | 想定より工数増 | VM Import/Export のバックアッププランを事前準備 |
| VPN 帯域不足 | SnapMirror 初期転送が遅延 | 初期転送は夜間バッチ、増分のみ日中実行 |
| FSx for ONTAP iSCSI パフォーマンス未達 | 顧客期待値と乖離 | プロビジョニングスループット引き上げ、Flash Cache 有効化 |

---

## 7. Go/No-Go 判定

### 判定会議

| 項目 | 記入欄 |
|------|--------|
| 日時 | ____年__月__日 |
| 参加者 | ビジネススポンサー、技術リード（両者） |
| 判定基準 | セクション 2 の成功指標すべて Go |

### 判定結果

| 判定 | 条件 | 次のアクション |
|------|------|-------------|
| **Go** | 全成功指標達成 | 本番移行計画の策定へ |
| **Conditional Go** | 一部指標未達だが許容可能 | 追加検証 or 構成変更後に再判定 |
| **No-Go** | 重大な技術的障壁あり | 代替ツール（CMC/MGN）の検討、または延期 |

---

## 8. 成果物一覧

| # | 成果物 | 作成者 | 提出先 |
|---|--------|--------|--------|
| 1 | PoC 環境構成図 | パートナー | 顧客技術リード |
| 2 | 移行手順書（ステップバイステップ） | パートナー | 顧客技術リード |
| 3 | パフォーマンスベンチマークレポート | パートナー | 顧客技術リード + スポンサー |
| 4 | コスト比較レポート（EBS vs FSx for ONTAP） | パートナー | ビジネススポンサー |
| 5 | Go/No-Go 判定資料 | 両者 | ビジネススポンサー |
| 6 | 本番移行計画（Go の場合） | パートナー | 顧客 |

---

## 付録: CloudFormation テンプレート

PoC 環境の AWS 側構築には、本リポジトリの CloudFormation テンプレートを使用可能:

```bash
aws cloudformation deploy \
  --template-file templates/poc-environment.yaml \
  --stack-name shift-toolkit-poc \
  --parameter-overrides \
    VpcCidr=10.0.0.0/16 \
    FsxnThroughput=512 \
    FsxnStorageCapacity=1024 \
    Ec2KeyPairName=<your-key-pair> \
    OnPremCidr=<on-prem-cidr> \
  --capabilities CAPABILITY_IAM
```

---

*テンプレートバージョン: 1.0 (2026-06-03)*
*本テンプレートは Shift Toolkit Early Preview 検証プロジェクトの成果物です。GA 後に手順の更新が必要な場合があります。*
