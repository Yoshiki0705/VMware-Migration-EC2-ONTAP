# 手順: AWS Transform による VMware → EC2 / FSx for ONTAP 移行

**目的**: AWS Transform（エージェント型 AI の移行サービス）を用いて、VMware ワークロードを Amazon EC2 へリホストし、ブロックデータを Amazon FSx for NetApp ONTAP へ配置する移行手順。

> ⚠️ **Public Preview / 2026-06 時点**。FSx for ONTAP を移行先とする機能は Public Preview。対応リージョン・UI・制約は変更されうる。GA 仕様としては扱わない。一次情報: [What's New](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/) / [AWS Transform pricing](https://aws.amazon.com/transform/pricing/)

---

## 0. 位置づけ

- AWS Transform は **移行ウェーブ全体（discovery → 計画 → コンピュート + ネットワーク + ストレージ）**を回す AWS ネイティブのオーケストレーター。
- VMware 移行エージェント自体の利用は **無料**。移行先の AWS リソース（EC2 / EBS / FSx for ONTAP / 転送等）は通常課金。
- **OS/ルートは EBS、データは FSx for ONTAP（iSCSI）** に収束する点は他手法と同じ（EC2 は FSx for ONTAP から直接ブート不可）。

---

## 1. 前提条件

公式ブログ（[Accelerating VMware migration](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/)）に基づき整理:

- **AWS Organizations** がセットアップ済み
- **AWS IAM Identity Center** がセットアップ済み（Transform へのユーザー割り当てに使用）
- AWS アカウント構成:
  - **移行計画アカウント**: AWS Transform を稼働させるアカウント（コントロール）
  - **ターゲットアカウント**: 移行先の EC2 / FSx for ONTAP を配置するアカウント
  - 両方同一 Organization 内。小規模なら1アカウントに統合も可
- AWS Transform の利用権限。アクセス方式:
  - **Web API 認証（SSO / IAM Identity Center もしくは Cookie）**
  - **SigV4（AWS 認証情報）**: アカウントが Transform API に対応している場合
- discovery 用インベントリ（以下のいずれか）:
  - **AWS Transform Discovery Collector OVA**（オンプレ vCenter にデプロイ。AWS 接続不要で情報収集、SQL Server検出にも対応）
  - **RVTools** エクスポート（CSV/XLSX）
  - **NetApp DII**
  - **Migration Evaluator / MPA**
  - **PowerCLI ベースコレクタ**（[aws-samples/sample-vmware-collector-v2](https://github.com/aws-samples/sample-vmware-collector-v2)。MPA/ME/RVTools形式で出力。性能データ最大365日を P95 で収集可能）
- 移行先 FSx for ONTAP ファイルシステム（Multi-AZ 推奨）と SVM
- オンプレ ↔ AWS のネットワーク（VPN/DX）

---

## 2. 操作手段（2通り）

### 2A. AWS マネジメントコンソール

- AWS Transform コンソールで VMware migration の transformation path を開始。
- discovery データ投入 → 依存マッピング → ウェーブ計画 → 移行先（EC2 / ネットワーク / **FSx for ONTAP ストレージ宛先**）選択 → 実行。

### 2B. AWS Transform MCP サーバー（本リポジトリで構成済み）

`.kiro/settings/mcp.json` に `awslabs.aws-transform-mcp-server` を設定済み。読み取り系は auto-approve、作成系（`create_workspace` / `create_job` 等）は都度承認。

代表的な操作フロー（自然言語で AI に依頼 → 内部で MCP ツール実行）:

1. 接続確認: `get_status`（SigV4 可否 / 認証状態）
2. エージェント確認: `list_resources(resource="agents", agentType="ORCHESTRATOR_AGENT")` → `vmware-migration-agent-v2` を確認
3. ワークスペース作成: `create_workspace`（※リソース作成。承認のうえ実行）
4. コネクタ作成: `create_connector`（S3 / コードソース。discovery データ用 S3 等）
5. ジョブ作成・開始: `create_job`（orchestratorAgent に VMware 移行エージェントを指定）
6. HITL タスク対応: `list_resources(resource="tasks")` → `get_resource(resource="task")` で内容確認 → **ユーザー承認後に** `complete_task`
7. 状態確認: `get_job_status` / 進行待ちは `adaptive_poll`

> **ガードレール**: HITL タスクは自動承認しない（必ず内容提示→ユーザー判断）。`create_*` / `control_job` / `complete_task` / `accept_connector` は都度確認。

---

## 3. 移行ステップ（ウェーブ）

公式ドキュメント（[UserGuide: Migrate servers](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-migrate-servers.html)）と [MGN agent automation blog](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migrations-with-aws-transform-and-mgn-replication-agent-installation-automation/) に基づくフロー:

### 3.1 全体ワークフロー

```text
┌────────────────────────────────────────────────────────────────────┐
│ AWS Transform VMware Migration Workflow                             │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  [Prerequisites + Migration Defaults]                              │
│    - Target accounts / Network infra / Inventory file              │
│    - EC2 recommendation preferences                                │
│    - MGN initialization (IAM roles auto-created)                   │
│    - EC2 launch template defaults                                  │
│                                                                    │
│  [Step 1] Set up migration wave                                    │
│    - Migration mode: Single-account or Multi-account               │
│    - Resource tagging (CreatedBy: AWSTransform)                    │
│    - Networking data → inventory                                   │
│    - Replication settings + Launch template                        │
│    - IP strategy: Static (with CIDR transform) or DHCP             │
│                                                                    │
│  [Step 2] Validate and confirm inventory                           │
│    - CSV/XLSX review: server names, EC2 types, subnets, SGs        │
│    - BYOL vs License Included / Tenancy options                    │
│                                                                    │
│  [Step 3] Deploy replication agents                                │
│    - 3 methods: Org tools / MGN Connector / Manual                 │
│    - MGN Connector: Linux VM on-prem → SSH/WinRM to source VMs     │
│    - Credentials via AWS Secrets Manager                            │
│    - Per-server status tracking                                    │
│                                                                    │
│  [Step 4] Data replication                                         │
│    - Continuous block replication to AWS (EBS staging area)         │
│    - FSx for ONTAP 宛先: ブロックデータを直接レプリケート          │
│      (Public Preview — intermediate storage 不要)                  │
│                                                                    │
│  [Step 5] Testing                                                  │
│    - Test instance launch → validation                             │
│                                                                    │
│  [Step 5b] Mark ready for cutover                                  │
│    - Application-level readiness confirmation                      │
│                                                                    │
│  [Step 6] Cutover                                                  │
│    - Final sync → Instance launch → Deployment approval (HITL)     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

> **Finalize は上の流れに含まれていない。** カットオーバー後に明示的に実行する不可逆な工程であり、**後片付けではなく物理容量が最大になる工程**である。FlexClone のスプリットに移行データ 1 本分の追加物理容量が一時的に必要になる（本検証では約 9 分間保持。[GA 検証レポート](./atx-fsxn-ga-verification.md) の 12.10）。アグリゲートの空きが移行データ量を下回る状態では実行しないこと。

### 3.2 MGN Connector によるエージェント自動デプロイ

AWS Transform は MGN Connector を用いてレプリケーションエージェントの大規模自動デプロイに対応。

| 項目 | 詳細 |
|------|------|
| Connector 実行環境 | オンプレ Linux マシン（SSH/WinRM でソース VM に接続） |
| Connector → AWS 通信 | SSM Hybrid Activation（HTTPS 443 outbound） |
| 認証情報管理 | AWS Secrets Manager に格納（per-server or shared） |
| マルチアカウント | 1 つの Connector で複数ターゲットアカウントに対応可 |
| 再利用 | ウェーブを跨いで再利用可能（Hybrid Activation 有効期間内: 30 日） |

#### クレデンシャル管理のセキュリティ要件

MGN Connector はソース VM に接続するため、SSH 鍵やパスワードを AWS Secrets Manager に格納する。以下のセキュリティ対策を実施すること。

| 対策 | 内容 |
|------|------|
| **暗号化キー** | CMK（Customer Managed Key）を推奨。AWS-managed key でも動作するが、本番では CMK でローテーション・アクセスポリシーを個別管理 |
| **アクセスポリシー** | Secret へのアクセスは MGN Connector の IAM ロール（`AWSApplicationMigrationConnectorManagementRole`）のみに限定。Resource-based policy で他プリンシパルを明示的に Deny |
| **ローテーション** | 移行ウェーブ完了ごとに Secret を削除 or ローテーション。長期放置しない |
| **監査** | CloudTrail で `secretsmanager:GetSecretValue` の呼び出し元を記録。想定外のアクセスを検知 |
| **Secret 構造** | 公式フォーマットに従う（下記参照） |

```json
{
  "WinConnectionProtocol": "HTTPS",
  "WinUserName": "<WINDOWS_USERNAME>",
  "WinPassword": "<WINDOWS_PASSWORD>",
  "LinuxUserName": "<LINUX_USERNAME>",
  "LinuxPrivateKey": "<LINUX_PRIVATE_KEY>",
  "LinuxHostKeyValidation": false
}
```

> **WinRM セキュリティ**: `WinConnectionProtocol` は **`HTTPS` を必須**とする。HTTP（5985）は暗号化されないため認証情報が平文で流れるリスクがある。Windows ソース VM で WinRM HTTPS リスナーを事前設定すること:
>
> ```powershell
> # ソース VM 上で WinRM HTTPS を有効化（自己署名証明書の例）
> $cert = New-SelfSignedCertificate -DnsName $env:COMPUTERNAME -CertStoreLocation Cert:\LocalMachine\My
> winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"$env:COMPUTERNAME`"; CertificateThumbprint=`"$($cert.Thumbprint)`"}"
> # ファイアウォールで 5986 を開放（5985 は閉じる）
> New-NetFirewallRule -Name "WinRM-HTTPS" -DisplayName "WinRM HTTPS" -Protocol TCP -LocalPort 5986 -Action Allow
> ```
>
> **本番向け**: 自己署名ではなく内部 CA 発行の証明書を使用。グループポリシーで WinRM HTTPS リスナーを一括配布すると大規模環境で効率的。

### 3.3 FSx for ONTAP 宛先のストレージレプリケーション（Public Preview）

> **What's New（2026-06-16）**: "AWS Transform replicates block storage data directly to FSx for ONTAP volumes as part of the same migration wave that handles compute and network, eliminating the need for intermediate storage platforms, separate migration tools, and the additional cost and risk they introduce."

**確定した情報:**

- ブロックストレージデータを FSx for ONTAP ボリュームに**直接レプリケート**
- 中間ストレージプラットフォーム不要
- compute + network と同一ウェーブ内で実行
- OS/ルートディスクは EBS（従来の MGN と同じ）
- データディスクの FSx for ONTAP 配置を同一ワークフロー内で処理

**未確認事項（引き続き要確認 — netapp-questions.md Q5, Q9）:**

- レプリケーションの内部メカニズム: AWS ネイティブのブロックコピーか、SnapMirror/FlexClone を利用するか
- FSx for ONTAP 上のストレージ形式: iSCSI LUN として配置されるか、別の形式か → **実機検証で判明予定**
- 移行後の ONTAP 機能（Snapshot 系譜）の引き継ぎ可否

> **ONTAP 系譜に関する補足（推論）**: AWS Transform は MGN ベースの**ブロックレベルレプリケーション**を使用する。これは ONTAP の SnapMirror（ボリュームレベルの論理レプリケーション）とは本質的に異なるメカニズムである。したがって、**移行後の FSx for ONTAP 上のデータは「新規 LUN/volume として作成された」状態になる可能性が高い**（Snapshot 履歴・SnapMirror 関係は引き継がれない）。これは制約ではなく設計上の特性であり、移行完了後に FSx for ONTAP 側で新規に Snapshot ポリシー / SnapMirror 関係を設定すれば運用上の問題はない。ただし「既存の Snapshot チェーンを維持したまま移行したい」要件がある場合は、**Shift Toolkit（SnapMirror ベース）の方が適する**。この点は実機検証で確認する。
>
> ⚠️ **上記は公開情報に基づく推定であり、確定情報ではない。実機検証で挙動を確認すること。**

> **移行後の LUN 配置には整える工程が要る。** 実測では 1 サーバーの全データディスクが 1 ボリュームの中に LUN として並んだ（[GA 検証レポート](./atx-fsxn-ga-verification.md) の 12.3）。**この配置が決めているのは性能ではなく復旧の粒度である**: Snapshot と SnapMirror はボリューム単位で動くため、同じボリュームの LUN は 1 回の Snapshot で相互整合が取れる代わりに個別には戻せない。LUN ごとに戻したい場合は移行後に `lun move` で分ける（本検証では未実行 — U5）。

### 3.4 対応リージョン

AWS Transform for VMware は [16 リージョンで利用可能](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/)（2026-06 時点）。

> **東京リージョン（ap-northeast-1）の対応状況**: AWS Transform for VMware の基本機能は東京リージョンで利用可能。ただし **FSx for ONTAP 宛先機能（Public Preview）が東京で利用可能かは未確認**。Preview 機能のリージョン展開は段階的であるため、実際にコンソールで確認するか、AWS SA 経由で確認すること。
>
> **確認方法**: AWS Transform コンソール（https://console.aws.amazon.com/transform/）にログインし、VMware migration ジョブ作成時のストレージ宛先選択で「FSx for ONTAP」オプションが表示されるかを確認。

---

## 4. 検証項目（AWS Transform 移行シナリオ）

| # | 検証項目 | 判定基準 | 備考 |
|---|---------|---------|------|
| T1 | discovery 取り込み | RVTools/DII が正しく解釈される | NetApp DII 連携の挙動を記録 |
| T2 | FSx for ONTAP 宛先の選択 UI | ウェーブ計画で FSx for ONTAP を宛先指定できる | マスキングの上スクショ |
| T3 | リホスト後 EC2 起動 | 正常ブート、status check OK | OS=EBS |
| T4 | データの FSx for ONTAP 配置 | ブロックデータが FSx for ONTAP ボリュームに配置 | iSCSI/プロトコルを記録 |
| T5 | データ整合性 | 移行前後 sha256sum 一致 | |
| T6 | ONTAP 機能継続 | Snapshot/SnapMirror/Efficiency が利用可能 | **要確認**: レプリ系譜の引き継ぎ |
| T7 | カットオーバー停止時間 | 実測・記録 | 計測区間: 最終同期開始（source server cutover 発動）→ ターゲット EC2 status check 2/2 pass まで |
| T8 | コスト | サービス無料、移行先インフラ実費を分解計上 | research.md 3.2.3 / 6章 Phase 3d |

---

## 5. 確認が必要な未確定事項（NetApp / AWS）

`netapp-questions.md` と連動。特に:

- AWS Transform の FSx for ONTAP 移行は内部で SnapMirror/FlexClone を使うのか、AWS ネイティブコピーか（移行後の ONTAP 系譜継続性に影響）
- FSx for ONTAP 宛先はブロック（iSCSI LUN）のみか、NFS データストア相当も対象か
- 対応リージョン（東京 ap-northeast-1 での Preview 可否）と制約・GA 時期

---

## 6. Shift Toolkit との比較・使い分け

> 詳細は [`research.md` セクション 3.2.3](./research.md) を参照。以下は最新情報に基づくサマリー。

### クイック判断フロー（所要 1 分）

```text
Q1: ソース VM は ONTAP NFS データストア上にあるか?
├─ No → AWS Transform 一択（Shift Toolkit は ONTAP NFS 必須）
│
└─ Yes
    Q2: 移行規模は?
    ├─ 大規模（100+ VM / マルチアカウント / NW 自動変換が必要）
    │   → AWS Transform を推奨
    │
    └─ 中小規模 / PoC / FlexClone の秒単位変換を活用したい
        Q3: ダウンタイム要件は?
        ├─ 最小化（分レベル）が必須 → AWS Transform（継続レプリ）
        └─ 30分〜2時間の計画停止が許容 → Shift Toolkit
```

> **注**: 両ツールとも無料。「どちらが安いか」ではなく「どちらが環境・要件に適するか」で選ぶ。

### 使い分けの判断軸

| 判断軸 | AWS Transform を選ぶ場合 | Shift Toolkit を選ぶ場合 |
|--------|-------------------------|------------------------|
| **ソース環境** | ONTAP 以外も混在（任意の VMware 環境） | ONTAP NFS データストア上の VM |
| **規模** | 中〜大規模（100+ VM、マルチアカウント） | 小〜中規模 / PoC |
| **オーケストレーション** | discovery → NW → compute → storage を一気通貫 | ディスク変換 + iSCSI 配置に特化 |
| **ダウンタイム** | 継続レプリケーション → 短時間カットオーバー | 計画停止（SnapMirror break + 変換） |
| **レプリケーション方式** | エージェント型（MGN — ブロックレベル継続同期） | SnapMirror（ボリュームレベル — 事前に同期完了） |
| **FSx for ONTAP 配置方式** | AWS ネイティブ（直接レプリケート — 内部メカニズム未公開） | VMDK → LUN 変換（FlexClone ベース、サイズ非依存） |
| **OS ディスク処理** | MGN が EBS ブート化を自動処理 | VMDK → RAW → S3 → AMI（or EBS Direct API） |
| **コスト（ツール）** | 無料（VMware migration） | 無料 |
| **ONTAP 運用継続性** | 要確認（SnapMirror 系譜の引き継ぎ可否が不明） | SnapMirror break 後に FSx for ONTAP ネイティブ |
| **ネットワーク変換** | AI 自動生成（vSwitch → VPC/SG） | 手動（Blueprint で Network Mapping） |
| **成熟度** | GA（基本機能）+ FSx for ONTAP 宛先は Public Preview | Early Preview |

### 組み合わせパターン（非排他）

```text
パターン A: AWS Transform 単体
  discovery → 計画 → NW → compute(EBS) + storage(FSx for ONTAP) → cutover
  → 最もシンプル。ソース環境を問わない。大規模に適する。

パターン B: Shift Toolkit 単体
  SnapMirror事前同期 → VM停止 → break → VMDK変換 → AMI + LUN → EC2起動
  → ONTAP 既存環境で FlexClone 高速変換が効く。中小規模 / PoC 向け。

パターン C: AWS Transform (計画 + NW) + Shift Toolkit (ストレージ変換)
  AWS Transform で discovery + NW + 計画を実施
  → データ移行は Shift Toolkit の SnapMirror + FlexClone で高速実行
  → 現時点では統合 API がないため手動オーケストレーションが必要
  → 将来的に DII 連携が拡張されれば自動化の可能性あり
```

### 移行ダウンタイムの比較

| 観点 | AWS Transform | Shift Toolkit |
|------|--------------|--------------|
| レプリケーション方式 | 継続的ブロック同期（agent-based） | SnapMirror（ボリューム単位 + final update） |
| カットオーバー停止時間 | 最終同期のみ（**推定**: 分〜10分程度） | 30 分〜2.5 時間（S3 upload + import-image が支配的） |
| 将来の改善 | — | EBS Direct API で大幅短縮見込み |

> **⚠️ distinction discipline**: AWS Transform のカットオーバー時間「分〜10分程度」は Public Preview のため**未実測の推定値**。Shift Toolkit の「30分〜2.5時間」は公式手順書のフローから計算した見積もり（実機検証前）。両方とも実機検証で確定値に更新する。

### 移行中のコスト構造

| コスト要素 | AWS Transform | Shift Toolkit |
|-----------|--------------|--------------|
| **ツール利用料** | 無料 | 無料 |
| **レプリケーション中のストレージ** | ステージング EBS（ターゲットリージョン、レプリ期間中課金）| FSx for ONTAP（SnapMirror 先。レプリ開始時点から SSD + スループット課金） |
| **S3 ステージング** | なし | Boot RAW の一時保管（数時間〜1日。$0.025/GB-月の按分） |
| **データ転送** | ソース → AWS（DX/VPN 経由。agent-based 継続転送） | ソース ONTAP → FSx for ONTAP（SnapMirror。DX/VPN 経由） |
| **移行先インフラ（継続）** | EC2 + EBS(boot) + FSx for ONTAP(data) | EC2 + EBS(boot) + FSx for ONTAP(data) |

> **注**: 移行先インフラコストは両方同一。差が出るのはレプリケーション**期間中**のステージングコスト。AWS Transform は継続レプリケーション中にステージング EBS が課金される（データ量 × 日数）。Shift Toolkit は FSx for ONTAP が SnapMirror 先として稼働するため、FSx for ONTAP の課金がレプリケーション設定時点から発生する。どちらも PoC レベルでは支配的なコストではない（数ドル/日）。

---

## 7. ロールバック手順

AWS Transform（MGN）による移行の各段階で問題が発生した場合のリカバリ手順。基本方針: **ソース VM は移行完了（カットオーバー）まで稼働し続けるため、レプリケーション停止 + テスト/カットオーバーインスタンスの破棄で安全に元の状態に戻れる。**

> **Shift Toolkit との重要な違い**: Shift Toolkit は SnapMirror break（不可逆操作）を行ってから変換するため、ロールバックには resync が必要。AWS Transform（MGN）は継続レプリケーションのため、ソース VM は常にアクティブで変更されない。ロールバックは「AWS 側のリソースを掃除する」だけで完了する。

### 7.1 ロールバック判断フロー

```text
問題の検出
  │
  ├─ Step 3（エージェントデプロイ）で失敗
  │   → ソース VM に変更なし。エージェント再インストール or 手動削除（7.2）
  │
  ├─ Step 4（レプリケーション）で失敗 or lag 解消しない
  │   → レプリケーション停止。ソース VM は無傷（7.3）
  │
  ├─ Step 5（テスト）でインスタンスに問題発見
  │   → テストインスタンス terminate。ソースに影響なし（7.4）
  │
  └─ Step 6（カットオーバー）後に問題発見
      → カットオーバーインスタンスを使い続けるか、ソースに戻すかの判断（7.5）
```

> **この判断フローが閉じるのは、移行先でクライアントが書き始めた瞬間である。** カットオーバー時点ではない。それ以降は「ソースに戻す」だけではデータロスになり、逆方向の同期（フェイルバック）を別途計画する必要がある（7.5）。

### 7.2 エージェントデプロイ失敗

ソース VM 上にレプリケーションエージェントのインストールが失敗したケース。

```bash
# 1. Linux: エージェントのアンインストール（インストール途中で残った場合）
sudo /opt/aws-replication/bin/aws-replication-uninstall

# 2. Windows: プログラムの追加と削除から AWS Replication Agent を削除
# または PowerShell:
# Start-Process msiexec.exe -ArgumentList "/x","{PRODUCT_CODE}","/quiet" -Wait

# 3. MGN コンソールで source server を Archive
# AWS CLI:
aws mgn update-source-server --source-server-id s-xxxxxxxxx --life-cycle '{"state":"DISCONNECTED"}'
aws mgn archive-source-server --source-server-id s-xxxxxxxxx
```

**対処**: 原因特定（ネットワーク / 認証 / ディスク容量）→ 修正後に再デプロイ。

### 7.3 レプリケーション失敗 / lag の未解消

エージェントは稼働しているが、レプリケーションが完了しない or エラーが出るケース。

```bash
# 1. レプリケーション状態確認
aws mgn describe-source-servers \
  --filters '{"isArchived": false}' \
  --query "items[].{id:sourceServerID,state:dataReplicationInfo.dataReplicationState}"

# 2. レプリケーション停止（source server を disconnect）
aws mgn disconnect-from-service --source-server-id s-xxxxxxxxx

# 3. 必要に応じて source server を Archive（完全に取り消す場合）
aws mgn archive-source-server --source-server-id s-xxxxxxxxx

# 4. ステージング EBS / レプリケーション用リソースは自動削除される
```

> **注**: レプリケーション停止してもソース VM には影響なし。エージェントはソース VM 上で idle 状態になるだけ。

### 7.4 テストインスタンスの問題

テスト起動した EC2 インスタンスが期待通り動作しないケース。

```bash
# 1. テストインスタンスを終了（MGN コンソール or CLI）
# AWS Transform UI: Testing フェーズで "Terminate test instances" を選択
# CLI:
aws mgn start-revert --source-server-id s-xxxxxxxxx

# 2. テストインスタンス関連リソース（EBS volumes, ENI）は自動クリーンアップ

# 3. 原因を修正（launch template / SG / IP / ドライバ等）

# 4. 再テスト
aws mgn start-test --source-server-ids s-xxxxxxxxx
```

> **注**: テスト中もレプリケーションは継続。テスト失敗→修正→再テストのサイクルは何度でも実行可能。

### 7.5 カットオーバー後のロールバック

カットオーバーが完了し、ターゲット EC2 が本番として起動した後に重大な問題が発見されたケース。

```text
判断ポイント:
  Q: カットオーバー後に新しいデータがターゲット EC2 に書き込まれたか?
  ├─ No（カットオーバー直後、まだ本番トラフィックを流していない）
  │   → ターゲット terminate + ソース VM を再起動（データロスなし）
  │
  └─ Yes（本番トラフィック開始済み、新規データあり）
      → 単純なロールバックはデータロスを伴う
      → 選択肢:
        A) ターゲット EC2 上で問題を修正して続行
        B) ターゲット上の新規データをバックアップ → ソースに戻す → データ統合
        C) 逆方向レプリケーション（ターゲット → ソース）を設定
```

```bash
# カットオーバー直後（新データなし）のロールバック:

# 1. ターゲット EC2 インスタンスを terminate
aws ec2 terminate-instances --instance-ids i-xxxxxxxxx

# 2. 関連 EBS / FSx for ONTAP リソースの確認と削除
aws ec2 describe-volumes --filters "Name=tag:CreatedBy,Values=AWSTransform"
# 必要に応じて削除

# 3. MGN で source server のステータスを確認
aws mgn describe-source-servers --filters '{"sourceServerIDs": ["s-xxxxxxxxx"]}'

# 4. ソース VM を再起動（VMware 側で power on）
# vCenter UI or PowerCLI: Start-VM -VM <VM_NAME>

# 5. DNS / ロードバランサーの切り戻し（ネットワーク変更した場合）
```

### 7.6 ロールバック後の確認項目

| 確認項目 | 方法 |
|---------|------|
| ソース VM が正常稼働 | vCenter UI: power state / VMware Tools heartbeat |
| アプリケーションの正常動作 | アプリケーション固有のヘルスチェック |
| レプリケーションリソースの掃除 | `aws mgn describe-source-servers` で archived 確認 |
| AWS 側の不要リソース | EC2 / EBS / ENI / SG で `CreatedBy: AWSTransform` タグリソースを確認 |
| コスト発生の停止 | ステージング EBS が削除されていること（レプリケーション停止後に自動） |

### 7.7 AWS Transform vs Shift Toolkit — ロールバック特性の比較

| 観点 | AWS Transform (MGN) | Shift Toolkit |
|------|---------------------|---------------|
| ソース VM の状態 | 常時稼働（レプリケーション中も変更なし） | カットオーバー時に shutdown → SnapMirror break |
| ロールバックの本質 | AWS 側リソースの削除のみ | SnapMirror resync + 中間ファイル削除 |
| 不可逆ポイント | カットオーバー後に新データが書かれた時点 | SnapMirror break の時点（resync で回復可能だが差分転送が必要） |
| ロールバック所要時間 | 即時（terminate + archive） | 10-30 分（resync 待ち） |
| リスクレベル | 低（ソース非破壊） | 中（resync 方向を間違えるとソース上書き） |

---

*本手順は Public Preview（2026-06 時点）に基づく検証用ドラフト。実機確認後に確定情報へ更新する。*

---

## 8. 検証実績（2026-06 実施）

### 8.1 AWS Transform 画面確認結果

2026-06-25 に AWS Transform コンソール（東京リージョン: ap-northeast-1）を操作し、以下を確認:

| 項目 | 確認結果 |
|------|---------|
| VMware Migration 機能 | **本番対応の機能**（Preview ではない）。画面上で「VMware環境からEC2への移行はプレビュー段階ではなく、本番対応の機能です」と明示 |
| UI | チャットベース（Agentic AI）。自然言語で移行操作を指示可能 |
| Workspace 作成 | `VMware-Migration-Test01` を作成済み（リクエスト → 数分で利用可能） |
| 移行プロセス説明 | 1. 評価 → 2. 計画 → 3. 実行 → 4. 検証、の 4 ステップ |
| ジョブ作成 | VMware Migration ジョブを新規作成し、評価と計画フェーズを開始可能 |

> **重要な訂正**: AWS Transform の VMware → EC2 移行は**本番機能（GA）**。FSx for ONTAP 宛先のストレージ移行のみが Public Preview。旧 MGN（Application Migration Service）が Transform に統合・進化したため、EBS 向けリホストは歴史のある成熟した機能。

### 8.2 AWS Transform と旧 MGN の関係整理

| 観点 | 説明 |
|------|------|
| 名称変遷 | AWS Server Migration Service → AWS MGN (Application Migration Service) → **AWS Transform に統合** |
| EBS 向け移行 | 旧 MGN 時代から存在する成熟機能。本番利用可能 |
| FSx for ONTAP 向け移行 | 2026-06 に Public Preview として追加された新機能 |
| UI/UX | 従来のコンソール型 → **Agentic AI（チャット型）に進化**。ジョブ作成・管理が対話形式 |

### 8.3 現時点の制約・確認中事項

- Workspace 作成後、ジョブ作成にタイムラグが発生する場合あり（「リクエストが開始されました」表示）
- FSx for ONTAP 宛先機能の東京リージョン対応状況は引き続き確認中
- vCenter 接続情報の準備が必要（Discovery フェーズで使用）

### 8.4 次ステップ

- [ ] VMware Migration ジョブを作成し、評価フェーズを開始
- [ ] vCenter 接続情報を投入して Discovery を実行
- [ ] FSx for ONTAP 宛先オプションの利用可否を確認
- [ ] テスト移行（boot disk のみ → EBS）を実行してダウンタイムを実測

---

## 参考リンク

- [AWS Transform VMware — Migrate servers (UserGuide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-migrate-servers.html)
- [AWS Transform VMware migration overview (UserGuide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-app-vmware.html)
- [AWS Transform now supports FSx for ONTAP (What's New, 2026-06-16)](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/)
- [Accelerating VMware migration: AWS Transform's new experience](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/) — E2E ウォークスルー
- [Accelerating VMware Cloud Migration with PowerCLI](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-cloud-migration-with-aws-transform-and-powercli/) — PowerCLI コレクタ
- [MGN replication agent installation automation](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migrations-with-aws-transform-and-mgn-replication-agent-installation-automation/) — 大規模エージェントデプロイ
- [Network Migration APIs](https://aws.amazon.com/blogs/migration-and-modernization/automate-large-scale-network-migration-using-aws-transform-network-migration-apis/) — NW 変換 API
- [Guidance for Automated Setup of AWS Transform for VMware](https://aws.amazon.com/solutions/guidance/automated-setup-of-aws-transform-for-vmware/) — テスト環境自動構築（2026-06）
- [AWS Transform top page (NY Summit 2026 announcements)](https://aws.amazon.com/transform/) — storage migration / continuous modernization
- [AWS Transform pricing](https://aws.amazon.com/transform/pricing/)
- [AWS Transform FAQ](https://aws.amazon.com/transform/faq/)
- [Modernize VMware workloads with agentic AI](https://aws.amazon.com/transform/vmware/)
- [Migrate VMware to Amazon EC2 & iSCSI-based FSx for ONTAP (NetApp Blog)](https://www.netapp.com/blog/aws-fsxn-blg-migrate-vmware-to-amazon-ec2-iscsi-based-fsx-for-ontap/)
- [aws-samples/sample-vmware-collector-v2](https://github.com/aws-samples/sample-vmware-collector-v2) — PowerCLI インベントリ収集ツール
- [Shift Toolkit EC2 移行手順書（本リポジトリ）](./shift-toolkit-ec2-procedure.md) — 比較対象
