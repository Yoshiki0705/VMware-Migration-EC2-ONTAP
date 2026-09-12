# NetApp 確認事項一覧 — VMware → EC2 / FSx for ONTAP 移行

> 目的: Shift Toolkit (Early Preview) と AWS Transform (FSx for ONTAP 宛先は 2026-08-30 に GA) を踏まえた
> 移行パスの確認。すべて公開情報ベースの技術質問であり、案件固有情報・社名・
> 内部識別子は含まない。

**背景（公開情報）:**

- NetApp Shift Toolkit が VMware ESXi → Amazon EC2 / FSx for ONTAP 移行を Early Preview で提供
- 2026-06-16: AWS Transform for migrations が FSx for ONTAP を移行先としてサポート（Public Preview）
  - [AWS What's New](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/)
- 2026-06-19: Shift Toolkit v8.0 リリース — EC2 + FSx for ONTAP が Early Preview として正式発表
  - [Tech ONTAP Blog: What's New in Shift v8.0](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)
- 2026-06-22: 公式手順書「Migrate VMs from VMware to AWS EC2 and FSx for ONTAP — Shift UI」入手
  - OS ディスク→EBS→AMI + データディスク→FSx for ONTAP LUN（iSCSI）のエンドツーエンドフローが確定

---

## 回答ステータス凡例

| ステータス | 意味 |
|-----------|------|
| ✅ 確認済み | 公開ブログ/ドキュメントで回答が得られた |
| 🔶 部分回答 | 情報はあるが詳細確認が必要 |
| ⬜ 未回答 | ブログ/ドキュメントでカバーされていない — 要確認 |

---

## 1. OS / ルートディスクのブート方式（最優先）

EC2 は AMI（EBS バックド）からのみブート可能で、FSx for ONTAP iSCSI LUN から直接起動はできない、という物理制約の確認。

| # | 質問 | 優先度 | ステータス |
|---|------|--------|-----------|
| Q1 | Shift Toolkit Early Preview は OS ディスクの AMI 変換まで含むか、データディスクの FSx for ONTAP 配置のみか? | Critical | ✅ 確認済み |
| Q2 | OS ディスクのみ別ツール（VM Import/Export, AWS MGN 等）併用が必要となるケースの想定はあるか? | Critical | ✅ 確認済み |
| Q3 | Shift Toolkit が変換した中間フォーマット（RAW/QCOW2）から AMI を作成する標準手順は提供されるか? | High | ✅ 確認済み |
| Q4 | EC2 起動後に必要な OS 修正（Nitro ドライバ、ENA、NVMe 対応）は自動化されるか、手動対応か? | High | ✅ 確認済み |

### Q1–Q4 回答根拠（公式 Shift Toolkit EC2 手順書 2026-06）

**一次情報**: "Migrate VMs from VMware to AWS EC2 and FSx for ONTAP" — Shift Toolkit UI ドキュメント

- **Q1**: ✅ **OS ディスクの AMI 変換まで含む。** 2つの方式を提供:
  1. **Amazon EBS Direct APIs**（推奨・最速）: EBS snapshot を直接作成
  2. **AWS VM Import/Export**: VMDK → RAW → S3 アップロード → AMI 変換
  - 現在の Preview リリースでは S3 import/export のみ有効。EBS Direct APIs は次回ドロップで有効化予定。

- **Q2**: ✅ **別ツール併用は不要。** Shift Toolkit がエンドツーエンドで OS→EBS→AMI + Data→FSx for ONTAP LUN を処理する。ワークフロー内で VM Import/Export サービスを内部利用するが、ユーザーが別途ツールを操作する必要はない。

- **Q3**: ✅ **標準手順として自動化されている。** 手順書記載のフロー:
  1. Boot disk VMDK → RAW 変換（ONTAP CLI 経由）
  2. RAW を S3 バケットにアップロード
  3. AWS VM Import/Export で AMI として登録
  - ユーザー操作は Shift Toolkit UI の Blueprint 作成 → Migrate ボタンのみ。

- **Q4**: ✅ **自動化される。** 手順書に明記:
  > "Shift toolkit is intelligent to automatically install the necessary cloud-init drivers"
  - **Linux**: cloud-init + EC2 datasource + Chrony を自動インストール（Ubuntu/Debian, SUSE 各対応）
  - **Windows**: EC2Launch v2 を自動インストール（MSI サイレントインストール）
  - **ENA ドライバ**: prepareVM フェーズで注入（現在の Preview では disabled、次回ビルドで有効化）
  - **VMware Tools**: 移行先で自動削除
  - **注**: prepareVM の自動実行は現 Preview 版では disabled。次回ドロップで有効化予定。手動での事前準備コマンドが手順書に記載されている。

## 2. AWS Transform と Shift Toolkit の関係

| # | 質問 | 優先度 | ステータス |
|---|------|--------|-----------|
| Q5 | AWS Transform の FSx for ONTAP 移行は内部で Shift Toolkit / FlexClone / SnapMirror を利用するのか、AWS ネイティブのブロックレプリケーションか? | Critical | ⬜ 未回答 |
| Q6 | NetApp DII 連携は AWS Transform の discovery（計画）フェーズのみか、移行実行フェーズにも及ぶか? | High | ⬜ 未回答 |
| Q7 | NetApp として、顧客への Shift Toolkit と AWS Transform の使い分け案内方針は（置き換え / 補完 / 並存）? | High | ⬜ 未回答 |
| Q8 | AWS Transform でコンピュート（ルート = EBS）、Shift Toolkit でデータ（FSx for ONTAP）を分担する構成は推奨構成として成立するか? | High | ✅ 確認済み |

### Q8 回答根拠（公式 Shift Toolkit EC2 手順書 2026-06）

Shift Toolkit 自身が「OS = EBS（AMI）、データ = FSx for ONTAP（iSCSI LUN）」を標準構成として実装。手順書の移行フロー:
1. Boot disk VMDK → RAW → S3 → AMI 登録
2. Data disk VMDK → FSx for ONTAP 上の LUN に変換
3. EC2 インスタンスを AMI から起動
4. データディスクを iSCSI 経由で EC2 ゲスト内にアタッチ

AWS Transform との分担は別の議論。Shift 単体でこの構成を完結できる。

> **注**: Q5–Q7 は Shift Toolkit の手順書・ブログいずれでも触れられていない。AWS Transform との関係は AWS/NetApp 双方に別途確認が必要。

## 3. FSx for ONTAP 移行先としての仕様

| # | 質問 | 優先度 | ステータス |
|---|------|--------|-----------|
| Q9 | AWS Transform の FSx for ONTAP 移行先はブロック（iSCSI LUN）のみか、NFS データストア相当も対象か? | High | ⬜ 未回答 |
| Q10 | 移行後に Snapshot / SnapMirror / FlexClone / Storage Efficiency はそのまま継続利用できるか（系譜・メタデータの引き継ぎ有無）? | Critical | ✅ 確認済み |
| Q11 | 東京リージョン（ap-northeast-1）で FSx for ONTAP 宛先が利用可能か? | Medium | 🔶 部分回答（**GA 時期は 2026-08-30 に確定。**[What's New](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)。東京での利用可否は未確認） |

### Q10 回答根拠（公式 Shift Toolkit EC2 手順書 2026-06）

手順書の移行フローから以下が確定:
- SnapMirror でソース ONTAP → FSx for ONTAP にレプリケーション
- 移行時に SnapMirror を break し、FSx for ONTAP 側を R/W 化
- データディスクは VMDK → LUN に変換後、FSx for ONTAP のネイティブ LUN として存在
- **移行後の FSx for ONTAP は通常運用と同等**: Snapshot / SnapMirror / FlexClone / Storage Efficiency はすべてネイティブに利用可能

**注意点**: SnapMirror は移行時に break されるため、ソースとの「Snapshot 系譜（継続的な差分チェーン）」は断絶する。移行後は FSx for ONTAP 側で新規に Snapshot ポリシーを設定する運用となる。これは設計上の意図（移行完了 = カットオーバー）であり、問題ではなく正常な動作。

## 4. 前提・運用

| # | 質問 | 優先度 | ステータス |
|---|------|--------|-----------|
| Q12 | Shift Toolkit の「ソース VM は ONTAP NFS データストア上が必須」という前提は EC2 移行パスでも同じか? | Medium | ✅ 確認済み |
| Q13 | 同時変換の並列数（最大 10 推奨）は EC2 移行パスでも同じか? | Low | 🔶 部分回答 |
| Q14 | Early Preview / Public Preview 検証結果の公開可能範囲（NDA 対象の有無）は? | Medium | ⬜ 未回答 |

### Q12–Q13 回答根拠（公式 Shift Toolkit EC2 手順書 2026-06）

- **Q12**: ✅ **同じ前提**。手順書に明記:
  > "Ensure the VM VMDKs are placed on NFSv3 volume (all VMDKs for a given VM should be part of the same volume)"
  - NFSv3 データストア限定（NFSv4 は非対応で UI に表示されない）
  - SAN ベースの VM は事前に Storage vMotion で NFS データストアに移動が必要

- **Q13**: 🔶 手順書に「Multiple VMs can be converted in parallel and the broken-off SnapMirror destination used for storing the converted VM disks accordingly」と記載。明示的な並列数上限は EC2 パスのドキュメントには記載なし。従来の 10 並列推奨が引き続き適用されると推定。

## 5. DR（災害対策）シナリオ

| # | 質問 | 優先度 | ステータス |
|---|------|--------|-----------|
| Q15 | VMware×ONTAP → EC2×FSx for ONTAP の DR は SnapMirror（継続レプリ）＋ EC2 復旧が推奨構成か? 他の推奨パターンはあるか? | High | ⬜ 未回答 |
| Q16 | AWS Transform は DR 用途（継続レプリケーション）に使えるか、それとも移行専用か?（弊チーム理解では移行専用） | High | ⬜ 未回答 |
| Q17 | FSx for ONTAP destination を break→RW 化して EC2 から iSCSI アタッチする復旧フローの推奨手順・注意点は? | High | ⬜ 未回答 |
| Q18 | フェイルバック（DR→オンプレ resync）の推奨手順と停止ウィンドウの目安は? | Medium | ⬜ 未回答 |
| Q19 | 本番レプリを断たずに DR テストする手法は FlexClone が推奨か? 他の方法は? | Medium | ⬜ 未回答 |
| Q20 | クロスリージョン DR（FSx for ONTAP→別リージョン FSx for ONTAP）の構成・制約は? | Low | ⬜ 未回答 |

> **注**: DR シナリオは Shift Toolkit v8.0 ブログのスコープ外。Shift は移行ツールであり DR ツールではない。DR 関連は別チャネル（AWS Storage Blog / NetApp Solutions ドキュメント / SA 確認）で回答を収集する。

---

## 確認方法のメモ

- Shift Toolkit v8.0 Early Preview の有効化: NetApp のサポート窓口に連絡（アドレスは Shift Toolkit v8.0 ブログに記載）
- Shift Toolkit ダウンロード: [MySupport Shift Toolkit ページ](https://mysupport.netapp.com/site/tools/tool-eula/netapp-shift-toolkit)（NetApp Support アカウント要）
- AWS Transform の FSx for ONTAP 宛先 UI: VMware migration の移行ウェーブ計画フロー内で確認（ジョブ作成・discovery データ投入が前提）

---

## 回答サマリー（2026-06-22 時点 — 公式手順書入手後）

| カテゴリ | ✅ 確認済み | 🔶 部分回答 | ⬜ 未回答 |
|---------|-----------|-----------|---------|
| 1. OS / ブート方式 | Q1, Q2, Q3, Q4 | — | — |
| 2. AWS Transform 関係 | Q8 | — | Q5, Q6, Q7 |
| 3. FSx for ONTAP 仕様 | Q10 | — | Q9, Q11 |
| 4. 前提・運用 | Q12 | Q13 | Q14 |
| 5. DR シナリオ | — | — | Q15–Q20 |

**確認済み**: 8/20 問 → **残存未回答（要 NetApp/AWS 確認）**: 9/20 問

> 注: Q1–Q4, Q8, Q10, Q12 は公式 Shift Toolkit EC2 手順書（2026-06）で確定。
> Q5–Q7（AWS Transform 関係）と Q15–Q20（DR）は Shift Toolkit のスコープ外のため別チャネルで確認。
