# Shift Toolkit — VMware ESXi → EC2 + FSx for ONTAP 移行手順書

**ステータス**: Early Preview  
**ソース**: 公式手順書 "Migrate VMs from VMware to AWS EC2 and FSx for ONTAP — Shift UI"（2026-06）  
**最終更新**: 2026-06-22

> **Note**: The VMware ESXi to AWS EC2 migration path in Shift Toolkit is an Early Preview feature.
> Specifications, constraints, and support scope may change. Enablement requires contact with NetApp support.

---

## 1. アーキテクチャ概要

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                        On-Premises                                        │
│  ┌─────────────┐     ┌──────────────────────────┐                        │
│  │ VMware ESXi │     │  ONTAP Cluster           │                        │
│  │  (vCenter)  │     │  ┌────────────────────┐  │                        │
│  │             │────▶│  │ NFS Volume (VMDKs) │  │                        │
│  │  Guest VMs  │     │  └────────────────────┘  │                        │
│  └─────────────┘     └──────────┬───────────────┘                        │
│                                 │ SnapMirror                              │
│  ┌──────────────────────┐       │                                        │
│  │ Shift Toolkit (Win)  │       │                                        │
│  │  - GUI / REST API    │       │                                        │
│  └──────────────────────┘       │                                        │
└─────────────────────────────────┼────────────────────────────────────────┘
                                  │ VPN / Direct Connect
┌─────────────────────────────────┼────────────────────────────────────────┐
│                        AWS VPC  │                                         │
│                                 ▼                                         │
│  ┌──────────────────────────────────────────────────┐                    │
│  │  Amazon FSx for NetApp ONTAP                     │                    │
│  │  ┌─────────────────────────────────────────┐     │                    │
│  │  │ SnapMirror Destination Volume (R/W化)   │     │                    │
│  │  │  - Boot VMDK → RAW → S3 → AMI          │     │                    │
│  │  │  - Data VMDKs → iSCSI LUNs             │     │                    │
│  │  └─────────────────────────────────────────┘     │                    │
│  └──────────────────────────┬───────────────────────┘                    │
│                             │ iSCSI (port 3260)                           │
│  ┌──────────────────────────▼───────────────────────┐                    │
│  │  Amazon EC2 Instance                             │                    │
│  │  ┌───────────────────┐  ┌──────────────────────┐│                    │
│  │  │ OS: EBS (gp3)     │  │ Data: FSx for ONTAP  ││                    │
│  │  │ (AMI からブート)   │  │ (iSCSI マルチパス)   ││                    │
│  │  └───────────────────┘  └──────────────────────┘│                    │
│  └──────────────────────────────────────────────────┘                    │
│                                                                           │
│  ┌────────────┐  ┌─────────────┐                                         │
│  │ S3 Bucket  │  │ IAM / SSM   │                                         │
│  │ (staging)  │  │ (vmimport)  │                                         │
│  └────────────┘  └─────────────┘                                         │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 前提条件

### 2.0 サポート対象ゲスト OS

移行前にソース VM のゲスト OS が以下のサポートマトリクスに含まれることを確認する。

| OS | サポートバージョン | 備考 |
|----|-------------------|------|
| **Windows Server** | 2016 / 2019 / 2022 / 2025 | 64-bit のみ |
| **Windows Desktop** | 10 / 11 | 64-bit のみ |
| **RHEL** | 7.2+ / 8.x / 9.x | SELinux enforcing 対応 |
| **CentOS** | 7.x | EOL 注意（2024-06 終了） |
| **AlmaLinux** | 7.x / 8.x / 9.x | CentOS 代替 |
| **Rocky Linux** | 8.x / 9.x | CentOS 代替 |
| **Ubuntu** | 18.04 / 22.04 / 24.04 | LTS のみ |
| **Debian** | 12 | — |
| **SUSE Linux Enterprise** | 12 / 15 | — |

> **非サポート（移行不可）:**
> - Windows Server 2008 / 2012（公式非サポート。一部成功報告あるが IP 自動設定不可）
> - RHEL / CentOS 5.x / 6.x
> - 32-bit OS 全般
> - FreeBSD / Solaris 等の非 Linux/Windows OS

<!-- TODO: スクリーンショット — Shift Toolkit UI のサポート OS 選択画面 -->

### 2.1 VM 要件

| 要件 | 詳細 |
|------|------|
| VMDK 配置 | **NFSv3** ボリューム上（同一 VM の全 VMDK が同じボリューム内） |
| VMware Tools | ゲスト VM で稼働中（準備フェーズで必要） |
| VM 状態（準備時） | RUNNING 状態 |
| VM 状態（移行時） | **POWERED OFF**（移行トリガー前に graceful shutdown） |
| NFSv4 | 非対応（UI に表示されない） |
| SAN ベース | 事前に Storage vMotion で NFS データストアに移動が必要 |

### 2.2 ストレージ要件

| 要件 | 詳細 |
|------|------|
| SnapMirror | ソース NFS volume → FSx for ONTAP 間でレプリケーション設定済み・健全状態 |
| FSx for ONTAP | 指定 VPC 内にプロビジョニング済み |
| ネットワーク接続 | オンプレミス ↔ AWS VPC 間の接続確立（DX or VPN） |

### 2.3 AWS 側の準備

#### IAM ポリシー（vmimport ロール）

> **本番環境での強化推奨**: 以下のポリシーは Early Preview / PoC 向けの構成です。本番環境では `Resource: "*"` を具体的な ARN に絞り込み、条件キー（`aws:RequestedRegion`、`ec2:ResourceTag` 等）でさらに制限することを推奨します。
>
> **注**: 以下は公式手順書記載のポリシーをそのまま転記。`s3:PutObject`（RAW → S3 アップロード用）が含まれていないが、Shift Toolkit が S3 マルチパートアップロードに別の認証パス（例: Shift Toolkit VM 自身の IAM Role / Instance Profile）を使用する可能性がある。実機検証で確認し、不足があれば追加すること。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3BucketAccess",
      "Effect": "Allow",
      "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::<BUCKET_NAME>"]
    },
    {
      "Sid": "S3ObjectAccess",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::<BUCKET_NAME>/*"]
    },
    {
      "Sid": "EC2MigrationActions",
      "Effect": "Allow",
      "Action": [
        "ec2:CopySnapshot",
        "ec2:RegisterImage",
        "ec2:ModifySnapshotAttribute",
        "ec2:DescribeSnapshots",
        "ec2:DescribeSnapshotAttribute",
        "ec2:DescribeImages",
        "ec2:DescribeImportSnapshotTasks",
        "ec2:DescribeInstances",
        "ec2:DescribeRegions"
      ],
      "Resource": "*"
    }
  ]
}
```

> **`Resource: "*"` の理由と本番向けガイダンス:**
>
> - `ec2:Describe*` 系アクションはリソースレベル権限に対応しないため `"*"` が必須。**「AWS 仕様上」ではなく出典で示します**: IAM の[ポリシーのトラブルシューティング](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_policies.html)が「`ec2:Describe` アクションはいずれもリソースレベル権限に対応しない」と明記しています。**個別のアクションを絞れるかは[サービス認可リファレンスの Resource types 列](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html)で確認してください。**
> - `ec2:CopySnapshot` / `ec2:RegisterImage` / `ec2:ModifySnapshotAttribute` は本番では以下のように絞る:
>
> ```json
> {
>   "Sid": "EC2MutationActionsScoped",
>   "Effect": "Allow",
>   "Action": [
>     "ec2:CopySnapshot",
>     "ec2:RegisterImage",
>     "ec2:ModifySnapshotAttribute"
>   ],
>   "Resource": [
>     "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:snapshot/*",
>     "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:image/*"
>   ],
>   "Condition": {
>     "StringEquals": {
>       "aws:RequestedRegion": "<REGION>"
>     }
>   }
> }
> ```
>
> - **認証情報のベストプラクティス**: Shift Toolkit に長期 Access Key を入力する代わりに、IAM ロール + AssumeRole（一時認証情報）の利用を検討する。オンプレミスから AssumeRole するには IAM Identity Center の OIDC 連携、または `sts:AssumeRole` で外部 ID を利用する方式がある。Early Preview では Access Key が求められるが、ローテーションポリシー（90 日以内）を適用し、移行完了後は即時無効化すること。
>
> **AssumeRole 構成例（本番向け）:**
>
> 1. 移行専用 IAM ユーザーに `sts:AssumeRole` のみ付与（直接の EC2/S3 権限なし）
> 2. 移行用 IAM ロールに上記ポリシー（EC2MigrationActions + S3）をアタッチ
> 3. ロールの信頼ポリシーで External ID を要求:
>
> ```json
> {
>   "Version": "2012-10-17",
>   "Statement": [{
>     "Effect": "Allow",
>     "Principal": { "AWS": "arn:aws:iam::<ACCOUNT_ID>:user/shift-migration-user" },
>     "Action": "sts:AssumeRole",
>     "Condition": {
>       "StringEquals": { "sts:ExternalId": "<UNIQUE_EXTERNAL_ID>" }
>     }
>   }]
> }
> ```
>
> 4. Shift Toolkit が AssumeRole をネイティブサポートしない場合は、ラッパースクリプトで一時認証情報を取得し環境変数に注入:
>
> ```powershell
> # PowerShell: 一時認証情報取得 → 環境変数セット
> $creds = aws sts assume-role `
>   --role-arn "arn:aws:iam::<ACCOUNT_ID>:role/ShiftMigrationRole" `
>   --role-session-name "shift-migration" `
>   --external-id "<UNIQUE_EXTERNAL_ID>" `
>   --query "Credentials" --output json | ConvertFrom-Json
> $env:AWS_ACCESS_KEY_ID = $creds.AccessKeyId
> $env:AWS_SECRET_ACCESS_KEY = $creds.SecretAccessKey
> $env:AWS_SESSION_TOKEN = $creds.SessionToken
> # 有効期限: デフォルト 1 時間（--duration-seconds で最大 12 時間に延長可）
> ```
>
> **ライフサイクル管理:**
> - 移行プロジェクト開始時に専用ユーザー/ロールを作成
> - 移行完了後に IAM ユーザーの Access Key を即時無効化・削除
> - 移行ロールは後続の DR テスト用に保持 or 削除を判断

#### セキュリティグループ

> **設計原則**: セキュリティグループはソースを最小限に絞る。`0.0.0.0/0` は使用しない。SG 間参照（SG-to-SG）を活用し、IP アドレスの直接指定を避ける。

**SG 1 — EC2 インスタンス（移行された VM）— Inbound:**

| ポート | プロトコル | ソース | 用途 |
|--------|-----------|--------|------|
| 22 | TCP/SSH | `<SHIFT_TOOLKIT_IP>/32` | Shift Toolkit からの Linux ポストローンチ検証 |
| 3389 | TCP/RDP | `<SHIFT_TOOLKIT_IP>/32` | Shift Toolkit からの Windows ポストローンチ検証 |
| 5986 | TCP/WinRM-HTTPS | `<SHIFT_TOOLKIT_IP>/32` | iSCSI イニシエータ設定（HTTPS のみ推奨） |
| ICMP | — | `<SHIFT_TOOLKIT_IP>/32` | 起動確認 ping |

> **本番向け推奨**: WinRM は 5986（HTTPS）のみに限定し、5985（HTTP）は開放しない。証明書を事前に設定すること。PoC 環境で 5985 を使用する場合は暫定運用と明示する。

**SG 2 — FSx for ONTAP ENI + VPC エンドポイント — Inbound:**

| ポート | プロトコル | ソース | 用途 |
|--------|-----------|--------|------|
| 3260 | TCP/iSCSI | SG 1（EC2 インスタンス SG） | EC2 → FSx for ONTAP データ LUN マウント |
| 443 | TCP/HTTPS | SG 1 + `<SHIFT_TOOLKIT_IP>/32` | ONTAP REST API（Shift Toolkit + EC2 から） |
| 22 | TCP/SSH | `<SHIFT_TOOLKIT_IP>/32` | ONTAP CLI 経由の VMDK→RAW 変換 |
| 11104-11105 | TCP | `<ON_PREM_ONTAP_IP>/32` | SnapMirror レプリケーション（ソース ONTAP から） |
| ICMP | — | SG 1 + `<SHIFT_TOOLKIT_IP>/32` | ヘルスチェック |

> **注**: `<SHIFT_TOOLKIT_IP>` はオンプレミスの Shift Toolkit Windows VM の IP アドレス。VPN/DX 経由で VPC に到達できることが前提。
> **注**: SnapMirror ポート (11104-11105) のソースは、オンプレミス ONTAP クラスタのインタークラスタ LIF の IP アドレスに限定する。

#### その他

- S3 バケット（VM Import/Export 用ステージング）
- SSM 用インスタンスプロファイル（IAM instance profile ARN）
- キーペア（EC2 ログイン用）

### 2.4 Shift Toolkit 有効化

1. NetApp のサポート窓口（アドレスは Shift Toolkit v8.0 ブログに記載）に連絡して EC2 Early Preview を有効化
2. Shift Toolkit インストールディレクトリの `config.json` を編集:
   ```json
   { "enableAmazonEC2": true }
   ```
3. NetApp Shift サービスを再起動

---

## 3. 移行手順

### Phase 1: サイト登録

1. Shift Toolkit UI にログイン
2. **Add New Site** → **Destination** を選択
3. 以下を入力:
   - Site Name: 任意の名前
   - Hypervisor: **AWS EC2**
   - Site Location / Connector: デフォルト
4. AWS 認証情報を入力:
   - Credential Name
   - AWS Access Key ID
   - AWS Secret Access Key
   - リージョン選択
5. FSx for ONTAP 接続情報を入力
6. **Create Site** をクリック

<!-- TODO: スクリーンショット — Add New Site > AWS EC2 選択画面 -->
<!-- TODO: スクリーンショット — AWS Credential / FSx for ONTAP 入力画面 -->

### Phase 2: リソースグループ作成

1. **Resource Groups** → **Create New Resource Group**
2. Source site を選択 → **Create**
3. ワークフロー選択: **Clone based Migration**（エンドツーエンド移行）
4. 移行対象 VM を選択（Datastore フィルターで NFSv3 データストアを選択）
5. Destination Site / AWS Entry / Datastore-to-Volume マッピングを設定
6. Boot Order / Boot Delay を設定（デフォルト: 3）
7. **Create Resource Group**

<!-- TODO: スクリーンショット — Resource Group 作成画面（VM 選択 + Datastore フィルター） -->

> **注**: 移行対象 VM は、本番 NFS データストアとは別の**専用 SVM/データストア**に事前に移動することを推奨（本番ワークロード分離）。

### Phase 3: Blueprint 作成

1. **Blueprints** → **Create New Blueprint**
2. Blueprint 名入力 + ソース/デスティネーション マッピング
3. S3 バケット指定（VM Import/Export ワークフロー用）
4. Resource Group 選択 → **Continue**
5. Execution Order 設定（複数リソースグループの場合）
6. Network Mapping（VPC サブネット/VLAN マッピング）
7. Storage Mapping（自動選択）
8. **VM Details 設定**:
   - サービスアカウント（Linux: sudoers、Windows: ローカル管理者）
   - EC2 設定: Security Group / Key Pair / IAM Instance Profile
   - IP 設定: DHCP or Static
   - VM リサイズ（CPU/RAM → 適切なインスタンスタイプ自動選択）
9. スケジュール設定（オプション: 30 分以上先の日時を指定）
10. **Create Blueprint**

<!-- TODO: スクリーンショット — Blueprint 作成画面（Network Mapping + VM Details） -->
<!-- TODO: スクリーンショット — EC2 設定（Security Group / Key Pair / Instance Profile） -->

> **現 Preview の制約**: prepareVM（ゲスト OS 準備の自動注入）は disabled。次回ビルドで有効化。現時点では手動で事前準備が必要（セクション 4 参照）。

### Phase 4: 移行実行

**前提**: VM が graceful shutdown 済み。

**Migrate** ボタンをクリック（またはスケジュール時刻に自動実行）。以下が自動実行される:

```text
 1. VMware snapshot 全削除（対象 VM）
 2. 新規 VMware snapshot 作成（Resource Group 単位）
 3. ソース ONTAP volume snapshot 作成
 4. SnapMirror update（最終差分をプッシュ）
 5. SnapMirror break（FSx for ONTAP 側を R/W 化）
 6. Boot disk: VMDK → RAW 変換
 7. Boot RAW → S3 アップロード
 8. Boot disk → AMI 登録（AWS VM Import/Export）
 9. Data disk: VMDK → LUN 変換（FSx for ONTAP 上）
10. iSCSI ターゲット準備:
    - igroup 作成/再利用
    - LUN → igroup マッピング（確定的 LUN ID）
    - SVM の target IQN 検出
    - ゲスト OS 判定（Linux/Windows）
11. EC2 インスタンス起動（AMI からブート）
12. EC2 ゲスト内で iSCSI 接続（データディスクマウント）
```

> **注**: ソース側の VMware snapshot と ONTAP snapshot はリカバリ参照として保持される。

### ダウンタイム構成と所要時間の見積もり

移行中の VM 停止時間（ダウンタイム）は、以下の構成要素の合計となる。**SnapMirror による事前レプリケーションが完了している前提**で、カットオーバー窓の大部分は「最終差分 + OS ディスク変換 + EC2 起動」である。

#### ダウンタイム構成要素

```text
|←─── ダウンタイム開始（VM shutdown）─────────────────────── EC2 起動完了 ───→|

[1] VM graceful shutdown                                    : 1-3 分
[2] VMware snapshot 削除 + 新規作成                         : 1-2 分
[3] ONTAP volume snapshot                                   : < 1 分
[4] SnapMirror final update（最終差分のみ）                 : 1-10 分 *
[5] SnapMirror break                                        : < 1 分
[6] Boot disk: VMDK → RAW 変換                              : 5-30 分 **
[7] Boot RAW → S3 アップロード                              : 5-60 分 ***
[8] S3 → AMI 登録（import-image）                           : 10-45 分 ****
[9] Data disk: VMDK → LUN 変換                              : 1-5 分（FlexClone ベース）
[10] iSCSI ターゲット準備                                   : < 1 分
[11] EC2 インスタンス起動                                   : 1-3 分
[12] iSCSI 接続 + データディスクマウント                    : 2-5 分
─────────────────────────────────────────────────────────────────────────────
合計見積もり                                                 : 30 分 〜 2.5 時間
```

> **\*** SnapMirror final update: VM shutdown 後の差分量に依存。事前に継続レプリケーションが走っていれば差分は極小（changed blocks のみ）。
>
> **\*\*** VMDK → RAW 変換: ONTAP CLI での変換。ディスクサイズと ONTAP のバックエンド性能に依存。
>
> **\*\*\*** S3 アップロード: ネットワーク帯域に強く依存。VPN 経由 vs Direct Connect で大きく異なる。FSx for ONTAP から同一リージョンの S3 へのアップロードであれば AWS 内部ネットワークを使用し高速。
>
> **\*\*\*\*** import-image: AWS 側の内部処理。サイズとリージョンの混雑度に依存。コントロール不可。

#### VMDK サイズ別の所要時間目安

以下は**推定値**であり、環境（ネットワーク帯域、ONTAP 性能、AWS リージョン負荷）により変動する。実機検証で確認すること。

| Boot VMDK サイズ | RAW 変換 | S3 アップロード | import-image | 合計（Boot のみ） |
|-----------------|----------|---------------|-------------|------------------|
| 30 GB | 3-5 分 | 3-10 分 | 10-20 分 | 約 20-35 分 |
| 50 GB | 5-10 分 | 5-15 分 | 15-25 分 | 約 25-50 分 |
| 100 GB | 10-20 分 | 10-30 分 | 20-35 分 | 約 40-85 分 |
| 200 GB | 20-30 分 | 20-60 分 | 30-45 分 | 約 70-135 分 |

| Data VMDK サイズ | LUN 変換 | iSCSI 準備 | 備考 |
|-----------------|----------|-----------|------|
| 任意（〜数 TB） | 1-5 分 | < 1 分 | FlexClone ベースのため**サイズにほぼ依存しない** |

> **重要**: データディスクの LUN 変換は FlexClone/メタデータ操作のため、1TB でも数分で完了する。ダウンタイムの支配的要因は**OS ディスクの S3 アップロード + import-image** である。

#### ダウンタイム短縮のための推奨事項

1. **Boot ディスクを小さく保つ**: OS + 最小限のアプリのみ。大容量データは Data disk（FSx for ONTAP LUN）に分離
2. **SnapMirror 事前同期を十分に実行**: カットオーバー前に差分を極小化
3. **Direct Connect を使用**: VPN 比で S3 アップロード速度が安定・高速化
4. **EBS Direct API（次回ドロップ）を待つ**: S3 ステージングが不要になり、ステップ 7-8 が大幅短縮される見込み
5. **移行ウィンドウをオフピーク時間帯に**: import-image の AWS 内部処理速度はリージョン負荷に影響される

---

## 4. ゲスト OS 事前準備（現 Preview 版・手動）

現 Preview 版では `prepareVM` が無効のため、以下を手動で実行する。

### 4.1 Linux（Ubuntu/Debian）

```bash
sudo apt-get update
sudo apt-get install -y cloud-init cloud-guest-utils chrony
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_ec2.cfg <<EOF
datasource_list: [ Ec2, None ]
datasource: { Ec2: { strict_id: false, timeout: 30, max_wait: 60 } }
EOF'
sudo systemctl enable --now chrony
sudo systemctl enable cloud-init-local cloud-init cloud-config cloud-final
```

### 4.2 Linux（RHEL / CentOS / AlmaLinux / Rocky Linux）

```bash
# cloud-init インストール（RHEL 8+ / AlmaLinux 8+ / Rocky 8+）
sudo dnf install -y cloud-init cloud-utils-growpart chrony

# iSCSI initiator（移行後の FSx for ONTAP データディスク接続に必要）
sudo dnf install -y iscsi-initiator-utils device-mapper-multipath
sudo systemctl enable iscsid multipathd

# RHEL 7 / CentOS 7 の場合は yum を使用
# sudo yum install -y cloud-init cloud-utils-growpart chrony iscsi-initiator-utils device-mapper-multipath

# EC2 datasource 設定
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_ec2.cfg <<EOF
datasource_list: [ Ec2, None ]
datasource: { Ec2: { strict_id: false, timeout: 30, max_wait: 60 } }
EOF'

# NTP 設定（Chrony）
sudo systemctl enable --now chronyd

# cloud-init サービス有効化
sudo systemctl enable cloud-init-local cloud-init cloud-config cloud-final

# (推奨) NetworkManager を有効化し、cloud-init によるネットワーク設定を許可
sudo systemctl enable NetworkManager

# (推奨) ifcfg レガシースクリプト無効化（RHEL 8+）
# cloud-init がネットワーク設定を管理するため、レガシースクリプトとの競合を防ぐ
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_network.cfg <<EOF
network:
  config: disabled
EOF'
```

> **RHEL 固有の注意点:**
> - RHEL 7 系は `yum` を使用。`dnf` は RHEL 8 以降で利用可能。
> - SELinux が enforcing の場合、cloud-init のコンテキストが正しく設定されているか確認: `restorecon -Rv /etc/cloud/`
> - RHEL のサブスクリプション登録が有効でないとパッケージインストールに失敗する。移行前にサブスクリプション状態を確認すること。
> - CentOS Stream 9 / AlmaLinux 9 / Rocky Linux 9 は上記コマンドでそのまま動作する。

### 4.3 Linux（SUSE/openSUSE）

```bash
VER=$( . /etc/os-release; echo $VERSION_ID )
sudo zypper addrepo --refresh \
  "http://download.opensuse.org/distribution/leap/$VER/repo/oss/" repo-oss
sudo zypper addrepo --refresh \
  "http://download.opensuse.org/distribution/leap/$VER/repo/non-oss/" repo-non-oss
sudo zypper addrepo --refresh \
  "http://download.opensuse.org/update/leap/$VER/oss/" repo-update
sudo zypper --gpg-auto-import-keys refresh
sudo zypper --non-interactive install \
  cloud-init cloud-init-config-suse growpart chrony curl
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_ec2.cfg <<EOF
datasource_list: [ Ec2, None ]
datasource: { Ec2: { strict_id: false, timeout: 30, max_wait: 60 } }
EOF'
sudo systemctl enable --now chronyd
sudo systemctl enable cloud-init-local cloud-init cloud-config cloud-final
```

### 4.4 Windows

PowerShell（管理者権限）:

```powershell
$tmp = $env:TEMP
Invoke-WebRequest `
  'https://s3.amazonaws.com/amazon-ec2launch-v2/windows/amd64/latest/AmazonEC2Launch.msi' `
  -OutFile "$tmp\EC2Launch.msi" -UseBasicParsing
Start-Process msiexec.exe -ArgumentList "/i","$tmp\EC2Launch.msi","/quiet" -Wait
```

### 4.5 準備スクリプトの配置場所

| OS | パス |
|----|------|
| Windows | `C:\NetApp` |
| Linux | `/NetApp` および `/opt` |

---

## 5. 移行後の検証

### 5.1 EC2 インスタンス確認

- AMI からのブートが正常か
- ネットワーク設定（IP アドレス）が期待通りか
- SSM Agent による接続が可能か

### 5.2 iSCSI データディスク確認

- `iscsiadm -m session`（Linux）or iSCSI Initiator（Windows）でセッション確認
- データディスクがマウントされ、データが整合しているか
- I/O 性能が期待通りか

### 5.3 iSCSI マルチパス設定

FSx for ONTAP（Multi-AZ）は ALUA（Asymmetric Logical Unit Access）をサポートし、preferred / non-preferred パスを提供する。EC2 インスタンスからのマルチパス設定により、可用性とスループットが向上する。

#### Linux（dm-multipath）

```bash
# 1. multipath がインストール済みであることを確認（セクション 4.2 で実施済み）
sudo systemctl status multipathd

# 2. /etc/multipath.conf を ONTAP 推奨設定で作成
sudo bash -c 'cat >/etc/multipath.conf <<EOF
defaults {
    find_multipaths yes
    user_friendly_names yes
}

devices {
    device {
        vendor                "NETAPP"
        product               "LUN.*"
        path_grouping_policy  group_by_prio
        path_selector         "service-time 0"
        path_checker          tur
        features              "3 queue_if_no_path pg_init_retries 50"
        prio                  ontap
        failback              immediate
        no_path_retry         queue
    }
}
EOF'

# 3. multipathd を再起動して設定を適用
sudo systemctl restart multipathd

# 4. iSCSI ターゲットを検出・ログイン
sudo iscsiadm -m discovery -t sendtargets -p <FSXN_ISCSI_IP>
sudo iscsiadm -m node --login

# 5. マルチパスデバイスの確認
sudo multipath -ll
```

> **期待される出力例:**
> ```
> mpath0 (3600a09...) dm-2 NETAPP,LUN C-Mode
> size=100G features='3 queue_if_no_path pg_init_retries 50' hwhandler='0' wp=rw
> |-+- policy='service-time 0' prio=50 status=active
> | `- 3:0:0:0 sdb 8:16 active ready running
> `-+- policy='service-time 0' prio=10 status=enabled
>   `- 4:0:0:0 sdc 8:32 active ready running
> ```

#### Windows（MPIO + iSCSI Initiator）

```powershell
# 1. MPIO 機能を有効化（再起動が必要な場合あり）
Install-WindowsFeature -Name Multipath-IO -IncludeManagementTools
# 再起動が求められた場合: Restart-Computer

# 2. MPIO に iSCSI デバイスを追加
New-MSDSMSupportedHW -VendorId "NETAPP" -ProductId "LUN C-Mode"
# 再起動後に適用: Restart-Computer

# 3. MPIO ポリシー設定（ラウンドロビン推奨）
Set-MSDSMGlobalDefaultLoadBalancePolicy -Policy RR

# 4. iSCSI Initiator サービス起動
Set-Service -Name MSiSCSI -StartupType Automatic
Start-Service MSiSCSI

# 5. iSCSI ターゲットに接続
New-IscsiTargetPortal -TargetPortalAddress <FSXN_ISCSI_IP>
Connect-IscsiTarget -NodeAddress <TARGET_IQN> -IsPersistent $true

# 6. 確認
Get-MSDSMAutomaticClaimSettings
Get-Disk | Where-Object { $_.BusType -eq "iSCSI" }
```

> **注**: FSx for ONTAP Multi-AZ 構成では、preferred ノードへのパスが `prio=50`（Active/Optimized）、standby ノードへのパスが `prio=10`（Active/Non-Optimized）となる。フェイルオーバー時は自動的にパスが切り替わる。

### 5.4 ONTAP 機能確認

- FSx for ONTAP 上の LUN に Snapshot が取得できるか
- FlexClone が正常動作するか
- Storage Efficiency（圧縮/重複排除）が有効か

---

## 6. 現 Preview 版の制約

| 項目 | 制約 | 今後の予定 |
|------|------|-----------|
| OS ディスク変換方式 | S3 Import/Export のみ | EBS Direct APIs を次回ドロップで有効化 |
| prepareVM 自動実行 | Disabled | 次回ビルドで有効化 |
| VMware Tools 自動削除 | UI で disabled 表記 | 次回ビルドで有効化 |
| ENA ドライバ自動注入 | prepareVM に含まれるが disabled | 同上 |

---

## 7. PoC コスト見積もり

以下は **1 VM（Boot 50GB + Data 200GB）を東京リージョンで 1 ヶ月運用**した場合の概算。移行期間中のみの一時的コストと継続コストを分けて記載する。

> **注**: 価格は 2026-06 時点の東京リージョン（ap-northeast-1）公開価格に基づく推定値。最新価格は [AWS Pricing Calculator](https://calculator.aws/) で確認すること。

### 7.1 移行時の一時コスト（Migration Window のみ）

| リソース | サイジング | 単価 | 数量 | 費用 |
|---------|-----------|------|------|------|
| S3 ストレージ（Boot RAW ステージング） | 50 GB × 数時間 | $0.025/GB-月 | 50 GB × 0.01 月 | ~$0.01 |
| S3 PUT/GET リクエスト | マルチパートアップロード | $0.0047/1000 req | ~100 req | ~$0.01 |
| データ転送（S3 → EC2 同一リージョン） | — | $0 | — | $0 |

**移行一時コスト合計: ~$0.02（無視できるレベル）**

### 7.2 継続的な月額コスト（移行後の運用）

| リソース | サイジング | 単価（東京） | 月額 |
|---------|-----------|-------------|------|
| **EC2 インスタンス** | m5.large（2 vCPU, 8 GiB） | $0.124/hr | ~$90 |
| **EBS gp3**（Boot） | 50 GB, 3000 IOPS, 125 MB/s | $0.096/GB-月 | ~$4.80 |
| **FSx for ONTAP**（SSD） | 200 GB provisioned | $0.252/GB-月 | ~$50.40 |
| **FSx for ONTAP** スループット | 128 MB/s | $0.583/MB/s-月 | ~$74.62 |
| **EBS Snapshot**（AMI 保持） | 50 GB（初月のみフル、以後増分） | $0.05/GB-月 | ~$2.50 |

**PoC 月額合計: ~$222/月（1 VM）**

### 7.3 コスト最適化のポイント

| 観点 | 推奨 |
|------|------|
| EC2 | PoC 中はスポットインスタンスまたはスケジュール起動で時間削減 |
| FSx for ONTAP | Single-AZ で PoC コストを約 40% 削減。本番は Multi-AZ |
| FSx for ONTAP Storage Efficiency | 圧縮 + 重複排除で実効使用量 30-50% 削減が典型 |
| FSx for ONTAP 容量プール | アクセス頻度の低いデータは自動階層化で $0.0252/GB-月 |
| S3 ステージング | 移行完了後に即削除（保持不要） |
| EBS Snapshot | 不要な AMI / Snapshot は定期削除 |

> **distinction discipline**: 上記はサンプルサイジングでの推定値。実際のコストはインスタンスタイプ、Storage Efficiency 効果、稼働時間、データ増加量により変動する。本番見積もりには [AWS Pricing Calculator](https://calculator.aws/) + FSx for ONTAP sizing tool を使用すること。

---

## 8. EBS Direct API ワークフロー（次回ドロップ・プレビュー）

次回ドロップで有効化される EBS Direct API 方式は、S3 ステージングを省略して OS ディスクの EBS snapshot を直接作成する。ワークフローの変更点は OS ディスクの作成方法のみで、データディスク（LUN 変換 + iSCSI アタッチ）の工程は同一。

**EBS Direct API の利点:**

- S3 アップロード不要 → 転送時間短縮
- リージョン/AZ/アカウントを跨いだ snapshot 作成が可能
- 推奨方式として位置づけ

---

## 9. ロールバック手順

移行の各段階で失敗が発生した場合のリカバリ手順を以下に示す。基本方針は「**ソース VM とソース ONTAP Snapshot が無事であれば、いつでもソースに戻れる**」こと。

### 9.1 ロールバック判断フロー

```text
移行失敗の検出
  │
  ├─ Phase 4 ステップ 1-5（SnapMirror break まで）で失敗
  │   → ソース VM はそのまま。SnapMirror resync で回復（8.2）
  │
  ├─ Phase 4 ステップ 6-8（Boot disk 変換 / S3 / AMI）で失敗
  │   → FSx for ONTAP 側は R/W 化済みだがデータは無傷
  │   → S3 オブジェクト / snapshot / AMI を削除し、SnapMirror resync（8.3）
  │
  ├─ Phase 4 ステップ 9-10（Data disk LUN 変換 / iSCSI）で失敗
  │   → AMI は登録済みだが EC2 は未起動 or 起動後にデータディスク欠損
  │   → AMI 登録解除 + LUN 削除 + SnapMirror resync（8.4）
  │
  └─ Phase 4 ステップ 11-12（EC2 起動 / iSCSI 接続）で失敗
      → EC2 インスタンス terminate + LUN unmap + SnapMirror resync（8.5）
```

### 9.2 SnapMirror break 前の失敗（最も軽微）

ソース環境に変更なし。FSx for ONTAP 側の SnapMirror は healthy のまま。

**対処**: 原因特定 → 再実行。特別な復旧操作は不要。

### 9.3 Boot disk 変換 / S3 アップロード / AMI 登録で失敗

SnapMirror は既に break 済み（FSx for ONTAP が R/W）。

```bash
# 1. S3 バケットから中間ファイルを削除
aws s3 rm s3://<BUCKET_NAME>/<VM_NAME>/ --recursive

# 2. 不完全な import-image タスクをキャンセル（タスク ID が取得できる場合）
aws ec2 cancel-import-task --import-task-id import-snap-xxxxxxxxx

# 3. 不完全な AMI / snapshot を削除（登録された場合）
aws ec2 deregister-image --image-id ami-xxxxxxxxx
aws ec2 delete-snapshot --snapshot-id snap-xxxxxxxxx

# 4. FSx for ONTAP 側の SnapMirror を resync（ソースへ戻す）
# ONTAP CLI（FSx for ONTAP 側）:
snapmirror resync -destination-path <SVM_NAME>:<VOLUME_NAME>
```

> **注**: `snapmirror resync` はデスティネーション上の変更を破棄し、ソースとの同期を再開する。変換途中の中間データは失われるが、ソースは無傷。
>
> **所要時間の目安**: resync はベースライン再転送ではなく**差分転送**（common snapshot からの増分）。移行フロー中に break 後に書き込まれたデータ（VMDK→RAW 変換の中間ファイル等）の量に依存するが、通常は元のフル SnapMirror 初期化より大幅に短い。目安: 100GB の変更で 10-30 分（ネットワーク帯域に依存）。

### 9.4 Data disk LUN 変換で失敗

Boot disk は AMI 化成功しているが、データディスクの LUN 変換が途中で止まった場合。

```bash
# 1. 作成された AMI を登録解除
aws ec2 deregister-image --image-id ami-xxxxxxxxx
aws ec2 delete-snapshot --snapshot-id snap-xxxxxxxxx

# 2. FSx for ONTAP 上の不完全な LUN を削除
# ONTAP CLI:
lun show -vserver <SVM_NAME> -volume <VOLUME_NAME>
lun delete -vserver <SVM_NAME> -path /vol/<VOLUME_NAME>/<LUN_NAME>

# 3. igroup が作成されていた場合は削除
igroup show -vserver <SVM_NAME>
igroup delete -vserver <SVM_NAME> -igroup <IGROUP_NAME>

# 4. SnapMirror resync
snapmirror resync -destination-path <SVM_NAME>:<VOLUME_NAME>
```

### 9.5 EC2 起動後の失敗（iSCSI 接続不可 / データ不整合）

EC2 は起動したが、データディスクが正しくマウントされない、またはデータ不整合が検出された場合。

```bash
# 1. EC2 インスタンスを停止・terminate
aws ec2 terminate-instances --instance-ids i-xxxxxxxxx

# 2. AMI を登録解除
aws ec2 deregister-image --image-id ami-xxxxxxxxx
aws ec2 delete-snapshot --snapshot-id snap-xxxxxxxxx

# 3. FSx for ONTAP 上の LUN をオフラインにして削除
# ONTAP CLI:
lun offline -vserver <SVM_NAME> -path /vol/<VOLUME_NAME>/<LUN_NAME>
lun delete -vserver <SVM_NAME> -path /vol/<VOLUME_NAME>/<LUN_NAME>
igroup delete -vserver <SVM_NAME> -igroup <IGROUP_NAME>

# 4. SnapMirror resync でソースとの同期を回復
snapmirror resync -destination-path <SVM_NAME>:<VOLUME_NAME>

# 5. ソース側の VM をパワーオン（VMware 上で復旧）
# vCenter UI or PowerCLI:
# Start-VM -VM <VM_NAME>
```

### 9.6 ロールバック後の確認項目

| 確認項目 | コマンド / 方法 |
|---------|----------------|
| SnapMirror が再同期中であること | `snapmirror show -destination-path <SVM>:<VOL>` → status: `Snapmirrored`, transfer-status: `Transferring` |
| ソース VM が正常起動すること | vCenter UI で VM の Power State / VMware Tools heartbeat を確認 |
| ソースデータが無傷であること | VM 内でアプリケーション整合性を確認 |
| AWS 側のリソースが掃除されたこと | `aws ec2 describe-images --owners self` / `aws ec2 describe-snapshots --owner-ids self` で不要リソースなし |
| S3 バケットが空であること | `aws s3 ls s3://<BUCKET_NAME>/<VM_NAME>/` → 空 |

### 9.7 ロールバック時の重要注意事項

- **ソース VMware snapshot は保持される**: 移行ワークフローがソース側に作成した VMware snapshot と ONTAP snapshot は「リカバリ参照」として残されている。ロールバック後にこれらを整理する場合は、データの整合性を確認した後に手動で削除する。
- **SnapMirror resync の方向**: 必ず `destination-path`（FSx for ONTAP 側）を指定する。逆方向に resync すると**ソースデータが上書きされる**。
- **partial success の判断**: Boot disk が AMI 化成功し、一部のデータディスクのみ失敗している場合、成功分を活かして失敗分のみ再実行する選択肢もある。ただし Early Preview 段階では全体ロールバック → 再実行を推奨。
- **移行後に本番稼働開始した後のロールバック**: EC2 上で新規データが書き込まれた後は、単純な「ソースに戻す」ロールバックではデータロスが発生する。カットオーバー判定後のロールバックは別途計画が必要（フェイルバック = 逆方向の SnapMirror 設定）。

---

## 10. 検証実績（2026-06 実施）

### 10.1 検証結果サマリー

| Blueprint | 構成 | 結果 | 備考 |
|-----------|------|------|------|
| bp-winmigrate-test | boot disk のみ（C ドライブのみ） | ✅ Migration Complete | 初回テスト。EBS のみ使用 |
| bp01 | 複数ディスク構成（boot + data） | ❌ Migration Error / Partially Healthy | Windows Firewall が原因で SSM Agent / iSCSI 接続に失敗 |
| bp-ec2-migrate | 複数ディスク構成（boot + data） | ✅ Active / Healthy | Firewall 設定見直し後に成功 |

### 10.2 実測タイミングデータ（bp-ec2-migrate）

Blueprint `bp-ec2-migrate` の移行ジョブ完走時の各ステップ所要時間:

| ステップ | 処理内容 | 所要時間 |
|---------|---------|---------|
| 1 | Checking if a snapshot can be triggered on the volumes | 0.5 秒 |
| 2 | Deleting existing snapshots for all VMs in the setup | 1.7 秒 |
| 3 | Triggering VM snapshots for resource groups at source before disk upload | 30.2 秒 |
| 4 | Triggering volume snapshots before disk conversion | 5.2 秒 |
| 5 | Updating SnapMirror relationships — final sync to FSx for ONTAP | 70.5 秒 |
| 6 | Breaking SnapMirror relationships | 2 分 40.5 秒 |
| 7 | Converting boot disk VMDKs to RAW | 12.7 秒 |
| 8 | Uploading boot disk RAW files to S3 | **68 分 5.1 秒** |
| 9 | Importing boot disks to AMIs | **36 分 20.6 秒** |
| 10 | Launching EC2 instances | 15.1 秒 |

**合計: 約 1 時間 49 分**

#### 分析

- **S3 アップロード（68 分）と AMI インポート（36 分）が全体の 95% を占める**。この 2 ステップがダウンタイムの支配的要因。
- SnapMirror 関連（final sync + break）は合計約 3 分 51 秒で高速に完了。
- VMDK → RAW 変換は 12.7 秒と高速（ONTAP CLI でのメタデータ操作のため）。
- **Shift Toolkit 8.1（次期バージョン）で EBS Direct API ベースに変更予定** → S3 アップロード + AMI インポートが不要になり、大幅な時間短縮が期待される。

### 10.3 FSx for ONTAP 側の確認結果

複数ディスク構成の移行成功後、FSx for ONTAP 上で iSCSI LUN が正常に作成・マッピングされていることを確認:

```text
FsxIdXXXXXXXXXXXXXXXXX::> lun show
Vserver   Path                            State   Mapped   Type        Size
--------- ------------------------------- ------- -------- -------- --------
fsxsvm01  /vol/ds_migtoaws_bk/win_testvm02-disk1-clone.lun
                                           online  mapped   linux        50GB
```

### 10.4 複数ディスク構成での失敗原因と回避策

初回の複数ディスク構成（bp01）では、以下の原因で失敗:

| 失敗箇所 | 原因 | 回避策 |
|---------|------|--------|
| FSx for ONTAP からのディスクアタッチ | Windows Firewall が iSCSI / SSM Agent 通信をブロック | 移行前に Windows Firewall で必要なポート（3260, 443, ICMP）を開放 |
| SSM Agent 接続 | Firewall + 通信経路の問題 | EC2 起動後に SSM Agent が AWS に到達できるよう SG / Route Table を確認 |

**本番向け教訓:**

- 移行前のゲスト OS 準備（セクション 4）に加え、**Windows Firewall の事前設定**が必須
- iSCSI 関連ポート（3260）、SSM Agent（443 outbound）、WinRM（5986）を事前に許可
- セキュリティグループだけでなく、ゲスト OS 内のファイアウォールも確認すること

### 10.5 今後の検証予定

- [ ] Linux VM での複数ディスク構成テスト
- [ ] 大容量ディスク（200GB+）での所要時間計測
- [ ] Shift Toolkit 8.1（EBS Direct API）リリース後の再検証

---

## 関連ドキュメント

- [research.md](./research.md) — 調査レポート全体
- [netapp-questions.md](./netapp-questions.md) — NetApp 確認事項一覧
- [fsxn-iscsi-setup.md](./fsxn-iscsi-setup.md) — FSx for ONTAP iSCSI 設定ガイド
- [Shift Toolkit Overview（NetApp 公式）](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)
- [What's New in Shift v8.0 ブログ](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)
