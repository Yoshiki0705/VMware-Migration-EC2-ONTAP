# VMware → EC2 + FSx for ONTAP 移行方式比較

**目的**: VMware 仮想マシンを AWS へ移行する主要方式を比較し、各方式の適用条件・制約・移行時間・ダウンタイム・Amazon FSx for NetApp ONTAP 活用可否を整理する。

**最終更新**: 2026-06-29  
**ステータス**: ドラフト（パートナー MTG 向けたたき台）

---

## 1. 比較対象方式

| # | 方式 | 概要 |
|---|------|------|
| A | **NetApp Shift Toolkit** | ONTAP NFS データストア上の VM を SnapMirror + FlexClone で EC2 + FSx for ONTAP に移行 |
| B | **AWS Transform** | AWS ネイティブのエージェント型移行サービス。旧 MGN が統合・進化。Agentic AI ベースの UI |
| C | **VM Import/Export** | VMDK を S3 経由で AMI 化する最もオーソドックスな方式 |
| D | **Veeam Restore to EC2** | 既存 Veeam バックアップから EC2 へリストアする方式 |

---

## 2. 比較表

| 観点 | Shift Toolkit | AWS Transform | VM Import/Export | Veeam Restore to EC2 |
|------|--------------|---------------|-----------------|---------------------|
| **主な用途** | VMware VM を EC2 + FSx for ONTAP へ移行 | AWS ネイティブな移行計画・実行（discovery → cutover） | VM イメージを AMI 化 | バックアップから EC2 へリストア |
| **FSx for ONTAP 活用** | ◎ 強い。データディスクを iSCSI LUN として直接配置 | ◎ FSx for ONTAP 宛先が GA（2026-08-30）。データ領域を iSCSI LUN として直接配置 | △ 基本は EBS 中心。FSx for ONTAP は別途設計 | △ 基本は EBS 中心。FSx for ONTAP は別途設計 |
| **boot disk** | EBS（VMDK → RAW → S3 → AMI） | EBS（MGN エージェントが自動処理） | EBS（import-image で AMI 化） | EBS（Veeam が EC2 化を処理） |
| **data disk** | FSx for ONTAP iSCSI LUN（FlexClone ベース） | EBS or FSx for ONTAP（Preview） | EBS 中心 | EBS 中心。FSx for ONTAP は別途検討 |
| **ソース環境の前提** | ONTAP NFS データストア上の VM **必須** | 任意の VMware 環境（ONTAP 不要） | 任意（VMDK/OVA をエクスポートできればOK） | Veeam でバックアップ取得済みの VM |
| **ダウンタイム** | 30 分〜2.5 時間（実測: 約 1 時間 49 分 ※50GB boot disk） | 継続レプリケーション → 短時間カットオーバー（推定: 分〜10 分） | 長い（数時間〜半日。ディスクサイズに比例） | 差分バックアップ活用で短縮余地あり |
| **レプリケーション方式** | SnapMirror（事前同期 + final update） | MGN エージェント（継続的ブロック同期） | なし（ワンショットコピー） | Veeam の差分バックアップ |
| **大容量 VM 適性** | 8.1 以降に期待（EBS Direct API） | 高い（継続レプリケーションのためサイズ影響小） | 低い（S3 upload + import に比例して時間増大） | Repository 帯域次第 |
| **OS 制限** | Shift Toolkit サポートマトリクス参照（VM Import 依存部分あり） | MGN サポートマトリクス参照 | [制限多い](https://docs.aws.amazon.com/vm-import/latest/userguide/prerequisites.html)（EOL OS、P2V、i386 非対応等） | VM Import 依存の可能性あり（要確認） |
| **操作性** | 専用 GUI（Blueprint ベース） | Agentic AI（チャット型 UI）+ コンソール | CLI 中心（aws ec2 import-image） | Veeam GUI（Restore to EC2 ウィザード） |
| **成熟度** | Early Preview（EC2 移行パス） | GA（EBS 向け / FSx for ONTAP 宛先とも） | GA（歴史あり） | GA（Veeam 利用企業には馴染みあり） |
| **ツール費用** | 無料 | 無料（VMware migration agent） | 無料 | Veeam ライセンス必要 |
| **ネットワーク変換** | 手動（Blueprint で Network Mapping） | AI 自動生成（vSwitch → VPC/SG マッピング） | 手動 | 手動 |
| **ONTAP 運用継続性** | ◎ SnapMirror break 後に FSx for ONTAP ネイティブ | △ 要確認（Snapshot 系譜の引き継ぎ可否が不明） | ✕ 新規ボリューム扱い | ✕ 新規ボリューム扱い |
| **複数ディスク構成** | ◎ boot=EBS, data=FSx for ONTAP iSCSI を同一ワークフローで処理 | ○ 同一ウェーブ内で処理（FSx for ONTAP 宛先は Preview） | △ ディスクごとに個別処理が必要 | △ 追加ディスクは別途設計 |

---

## 3. 方式選定ガイド

### 3.1 クイック判断フロー

```text
Q1: ソース VM は ONTAP NFS データストア上にあるか?
├─ No → Q4 へ
│
└─ Yes
    Q2: 移行規模は?
    ├─ 大規模（100+ VM / マルチアカウント / NW 自動変換が必要）
    │   → AWS Transform を推奨
    │
    └─ 中小規模 / PoC
        Q3: ダウンタイム要件は?
        ├─ 最小化（分レベル）が必須 → AWS Transform（継続レプリ）
        └─ 30分〜2時間の計画停止が許容 → Shift Toolkit

Q4: ソースが ONTAP NFS でない場合
    Q5: 既存 Veeam 環境があるか?
    ├─ Yes → Veeam Restore to EC2 を検討
    └─ No
        Q6: 規模・自動化要件は?
        ├─ 大規模 / 自動化必須 → AWS Transform
        └─ 小規模 / 単発 → VM Import/Export（最もシンプル）
```

### 3.2 VM 特性別の推奨方式

| VM 特性 | 推奨方式 | 理由 |
|---------|---------|------|
| boot disk のみ（C ドライブのみ） | AWS Transform or Shift Toolkit | どちらも対応。規模で選択 |
| 複数ディスク構成（C + D ドライブ等） | Shift Toolkit or AWS Transform (Preview) | FSx for ONTAP への自動配置が可能 |
| 大容量 VM（500GB+） | AWS Transform | 継続レプリケーションのためサイズ影響小 |
| レガシー OS（Windows 2012 等） | VM Import + 手動調整 | Shift Toolkit / Transform とも非サポートの可能性 |
| 短停止要件（分レベル） | AWS Transform | 継続レプリケーション + 最終同期のみ |
| 既存 Veeam 環境あり | Veeam Restore to EC2 | 追加ツール不要。差分バックアップ活用 |
| FSx for ONTAP 積極活用 | Shift Toolkit | FlexClone ベースの高速 LUN 変換。ONTAP 系譜維持 |

---

## 4. ダウンタイム比較（実測 / 推定）

| 方式 | boot 50GB の場合 | boot 100GB の場合 | 備考 |
|------|-----------------|-----------------|------|
| **Shift Toolkit** | **実測: 約 1 時間 49 分** | 推定: 2〜3 時間 | S3 upload (68分) + AMI import (36分) が支配的 |
| **AWS Transform** | 推定: 5〜15 分 | 推定: 5〜15 分 | 継続レプリのため boot サイズに依存しにくい |
| **VM Import/Export** | 推定: 2〜2.5 時間 | 推定: 4〜5 時間 | VM 停止→エクスポート→S3→import の全工程 |
| **Veeam** | 推定: 要検証 | 推定: 要検証 | 差分バックアップの頻度・Repository 性能に依存 |

> **⚠️ distinction discipline**: Shift Toolkit の値は実測。AWS Transform / VM Import / Veeam は推定値。実機検証で確定値に更新する。

### Shift Toolkit 実測データ内訳

```text
SnapMirror 関連（steps 1-6）:  約  3分51秒（全体の 3.5%）
VMDK → RAW 変換:               12.7秒（無視できるレベル）
S3 アップロード:                68分 5.1秒（全体の 62%）  ← ボトルネック①
AMI インポート:                 36分20.6秒（全体の 33%）  ← ボトルネック②
EC2 起動:                       15.1秒
```

**Shift Toolkit 8.1 での改善見込み**: EBS Direct API により S3 + AMI インポートのステップが不要になり、推定ダウンタイムは **5〜15 分**に短縮される見込み。

---

## 5. 各方式の主な考慮点

### 5.1 Shift Toolkit

**強み:**

- FlexClone ベースのデータディスク変換（サイズ非依存、秒単位）
- FSx for ONTAP への直接 iSCSI LUN 配置
- SnapMirror break 後の ONTAP 機能（Snapshot / SnapMirror / Efficiency）がネイティブに継続
- GUI（Blueprint）による一括管理

**考慮点:**

- ソース VM が ONTAP NFS データストア上にある必要がある
- 現行版は S3 → AMI import がボトルネック（8.1 で解消見込み）
- Early Preview のため仕様変更の可能性あり
- 移行前のゲスト OS 準備（cloud-init / EC2Launch / iSCSI initiator）が手動
- 複数ディスク構成では Windows Firewall / SSM Agent / iSCSI 通信の事前設定が重要

### 5.2 AWS Transform

**強み:**

- ソース環境を問わない（ONTAP 不要）
- 継続レプリケーションによる短時間カットオーバー
- discovery → 計画 → NW 変換 → 実行の一気通貫オーケストレーション
- Agentic AI による対話型操作
- マルチアカウント / 大規模移行に対応
- EBS 向け移行は GA（成熟）

**考慮点:**

- FSx for ONTAP 宛先は 2026-08-30 に GA。ブートは常に Amazon EBS になる
- ONTAP Snapshot 系譜の引き継ぎ可否が不明（新規 LUN/volume として作成される可能性）
- レプリケーションエージェントのソース VM へのインストールが必要
- 継続レプリケーション中のステージング EBS コストが発生
- AWS Organizations + IAM Identity Center のセットアップが前提

### 5.3 VM Import/Export

**強み:**

- もっともシンプル・オーソドックス
- 追加ツール不要（AWS CLI のみ）
- 小規模・単発の移行に適する

**考慮点:**

- **ダウンタイムが長い**（VM 停止→エクスポート→S3 upload→import の全工程が停止時間）
- 差分同期なし（ワンショットコピー）
- OS 制限が多い（EOL OS、P2V 由来、i386 非対応、UEFI 制約等）
- 2026-04-01 以降 i386 アーキテクチャのサポート停止
- 複数ディスクの個別処理が必要
- 大容量 VM では現実的でない所要時間になる

### 5.4 Veeam Restore to EC2

**強み:**

- 既存 Veeam 環境があれば追加ツール不要
- GUI 操作しやすい
- 差分バックアップを活用できる場合、ダウンタイム短縮余地あり
- DR / テストリストア用途にも説明しやすい
- VM ゲストへのエージェント導入不要のケースあり

**考慮点:**

- 内部的に VM Import 相当の制約を受ける可能性あり（要確認）
- FSx for ONTAP へのデータディスク配置は別途設計が必要
- Veeam ライセンス・環境構築・Repository 配置設計が必要
- ネットワーク帯域と Repository 性能がボトルネックになりうる
- 本番移行方式としては運用設計と手順標準化が必要

---

## 6. 組み合わせパターン

各方式は排他ではなく、VM 特性に応じて併用可能:

```text
パターン A: AWS Transform 単体
  → 最もシンプル。ソース環境を問わない。大規模に適する。

パターン B: Shift Toolkit 単体
  → ONTAP 既存環境で FlexClone 高速変換が効く。中小規模 / PoC 向け。

パターン C: AWS Transform (計画 + NW) + Shift Toolkit (ストレージ変換)
  → 大規模移行の計画・NW は Transform、データ移行は Shift Toolkit。

パターン D: 方式混在（VM 特性別に使い分け）
  → 例: 通常 VM は AWS Transform、ONTAP NFS 上の大容量 VM は Shift Toolkit、
       レガシー OS は VM Import、既存 Veeam 利用 VM は Veeam。
```

---

## 7. パートナー MTG 確認事項

### AWS Transform 関連

- [ ] FSx for ONTAP 宛先 Preview の東京リージョン対応状況
- [ ] 複数ディスク VM における boot / data disk の配置先制御方法
- [ ] 旧 MGN との機能差分の整理
- [ ] カットオーバー時の実測ダウンタイム（経験値）

### Shift Toolkit 関連

- [ ] 現行バージョンの VM Import 依存範囲
- [ ] 8.1 の EBS Direct API 化によるステップ短縮の詳細
- [ ] 複数ディスク構成での SSM Agent / iSCSI 前提条件の整理

### VM Import 関連

- [ ] 最近の OS サポート状況で注意すべき点
- [ ] 過去案件での典型的な失敗例
- [ ] EOL OS を含む場合の顧客説明方法

### Veeam 関連

- [ ] Restore to EC2 が内部的に VM Import を使用しているか確認
- [ ] VM Import の OS 制限を同様に受けるか
- [ ] FSx for ONTAP をデータディスクとして使う場合の構成パターン

---

## 8. Next Action

| タスク | 担当 | 期限 |
|--------|------|------|
| Shift Toolkit 検証結果の整理 | NetApp（自チーム） | 今週中 |
| 複数ディスク構成の成功条件整理 | NetApp（自チーム） | 今週中 |
| AWS Transform Workspace でジョブ作成・テスト移行実行 | NetApp（自チーム） | 来週前半 |
| AWS Transform の FSx for ONTAP 対応制限確認 | パートナー SA / NetApp | 来週前半 |
| VM Import の対象 OS・制限整理 | パートナー SA / NetApp | 来週前半 |
| Veeam Restore to EC2 の検証 | NetApp（自チーム） | 来週中 |
| 比較表ドラフト完成 | NetApp（自チーム） | 来週中 |
| 顧客向け説明観点レビュー | 全員 | 次回 MTG |

---

## 関連ドキュメント

- [Shift Toolkit EC2 移行手順書](./shift-toolkit-ec2-procedure.md)
- [AWS Transform 移行手順書](./aws-transform-migration-procedure.md)
- [VM Import/Export 手順書](./vm-import-procedure.md)
- [FSx for ONTAP iSCSI 設定ガイド](./fsxn-iscsi-setup.md)
- [調査レポート](./research.md)
