# NetApp Shift Toolkit — VMware ESXi to EC2 / FSx for ONTAP 検証調査レポート

**作成日**: 2026-06-03  
**著者ポジション**: Amazon FSx for NetApp ONTAP 担当 / AWS Community Builder  
**ステータス**: 調査フェーズ（Early Preview 検証前）

> ⚠️ **本文は 2026-06-03 時点のスナップショットです。** 以降、AWS Transform の FSx for ONTAP 宛先は **2026-08-30 に GA** しました。本文中の「Public Preview」の記述は 当時のものです。[（GA の一次情報）](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/) GA 後の実機検証は [検証レポート](atx-fsxn-ga-verification.md) にあります。

---

## 1. エグゼクティブサマリー

私は、Amazon FSx for NetApp ONTAP を担当する立場、また AWS Community Builder として、VMware ワークロードの次の移行先を検討しているお客様に向けて、NetApp Shift Toolkit の VMware ESXi から Amazon EC2 / FSx for ONTAP への移行プレビューを検証しています。

NetApp Shift Toolkit は、VM を異なるハイパーバイザー間で移行し、仮想ディスク形式の変換を支援するスタンドアロンツールです。NetApp のドキュメントでは、VMware ESXi、Microsoft Hyper-V、Oracle Linux Virtualization Manager、Red Hat OpenShift Virtualization などを対象に、ハイパーバイザーをまたいだ VM 移行を簡素化・高速化する製品として説明されています。[（出典）](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)

今回注目している Early Preview は、**VMware ESXi から AWS EC2 への移行において、OS ディスクを EBS に変換し、データディスクを Amazon FSx for NetApp ONTAP 上に配置するアプローチ**です。FSx for ONTAP は、AWS 上でフルマネージドの NetApp ONTAP ファイルシステムを利用できるサービスであり、NFS、SMB、iSCSI といったプロトコル、Snapshot、clone、replication、compression、deduplication などの ONTAP データ管理機能を AWS のマネージドサービスとして利用できます。[（出典）](https://aws.amazon.com/documentation-overview/netapp-ontap/)

**この検証のポイント**は、「VMware から AWS へ移行する」ことだけではありません。既存の VMware / ONTAP 運用で培ったストレージ運用モデルをできるだけ活かしながら、Amazon EC2 と FSx for ONTAP を組み合わせ、クラウドネイティブな運用・拡張性・コスト最適化へつなげられるかを確認することにあります。

AWS Storage Blog でも、VMware ワークロードを Amazon EC2 と Amazon FSx for NetApp ONTAP へ移行する動きは、単なるライセンス回避ではなく、AWS のコスト効率、柔軟性、信頼性、セキュリティを活用するインフラモダナイゼーションの機会として説明されています。[（出典）](https://aws.amazon.com/blogs/storage/expedite-vmware-migration-to-amazon-ec2-and-amazon-fsx-for-netapp-ontap-using-bluexp-workload-factory-for-aws-migration-advisor/)

> ⚠️ **注意**: VMware ESXi to AWS EC2 の Shift Toolkit 対応は Early Preview の位置づけです。
> **2026-06-19 更新**: Shift Toolkit v8.0 ブログにて、OS ディスクの EBS 変換とデータディスクの FSx for ONTAP 配置の**両方**をカバーすることが確認されました（[出典](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)）。利用には NetApp のサポート窓口への連絡が必要であり、検証時点の仕様・制約・サポート範囲は変更される可能性があります。

---

## 2. Shift Toolkit 機能概要

### 2.1 ツール概要

| 項目 | 内容 |
|------|------|
| 提供元 | NetApp（無償） |
| 動作環境 | Windows のみ（スタンドアロン GUI アプリケーション） |
| 前提条件 | ONTAP 9.14.1 以降 |
| ダウンロード | [NetApp Support Site](https://mysupport.netapp.com/site/tools/tool-eula/netapp-shift-toolkit) |
| REST API | あり（自動化ワークフロー対応） |

> 出典: [Shift Toolkit Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)

### 2.2 サポートされるハイパーバイザー

**ソース（移行元）:**

- VMware ESXi（vSphere 7.0.3 以降で検証済み）
- Microsoft Hyper-V（Windows Server 2019/2022/2025）

**ターゲット（移行先）:**

- Microsoft Hyper-V
- VMware ESXi
- Red Hat OpenShift Virtualization（4.17 以降）
- Oracle Linux Virtualization Manager（4.5 以降）
- Proxmox VE（9.x 以降）
- KVM（ディスク変換のみ：VMDK → QCOW2/RAW）

**ディスクフォーマット変換:**

- VMDK → VHDX（Hyper-V 向け）
- VMDK → QCOW2（KVM 互換ハイパーバイザー向け）
- VMDK → RAW（KVM 互換ハイパーバイザー向け）
- VHDX → VMDK（VMware 向け）

> 出典: [Supported Versions](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-supported-versions.html)

**注意**: 現リリースでは、エンドツーエンドの VM 移行（ディスク変換 + VM 作成 + ネットワーク設定）は Hyper-V、VMware、OpenShift、Oracle Virtualization でのみサポート。KVM 向けはディスク変換のみ。

### 2.3 サポート対象ゲスト OS

**Windows:**

- Windows 10/11
- Windows Server 2016/2019/2022/2025

**Linux:**

- RHEL 7.2+/8.x/9.x
- CentOS 7.x
- Alma Linux 7.x
- Ubuntu 2018/2022/2024
- Debian 12
- SUSE Linux Enterprise Server 12/15

> 出典: [Supported Versions](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-supported-versions.html)

### 2.4 FlexClone による高速ディスク変換の仕組み

Shift Toolkit の変換速度の核心は ONTAP FlexClone テクノロジーにある。

**動作原理:**

1. **単一ボリューム・マルチプロトコル**: ONTAP では1つのボリュームに NFS と CIFS/SMB の両方でアクセス可能。VMware ESXi は NFS でアクセスし、Hyper-V は SMB でアクセスする
2. **FlexClone**: データコピーなしでファイルまたはボリューム全体を高速クローン。ストレージシステム上の共通ブロックを複数のファイル/ボリューム間で共有
3. **VM ディスク変換**: FlexClone を利用して VMDK を VHDX/QCOW2 等に変換。クローンと変換を1ステップで実行

**結果**: 1TB の VMDK ファイル変換が通常数時間かかるところ、**数秒〜数分**で完了する。

> 出典: [Shift Toolkit Overview - How Shift toolkit works](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)

### 2.5 移行ワークフロー（ステップバイステップ）

**Phase 1: 準備（Prepare VM）**

1. Shift Toolkit が VMware/ターゲットハイパーバイザーに接続し、ホスト・VM のメタデータを収集
2. VM を選択し、Shift Toolkit が必要なスクリプトを注入
   - VMware Tools 削除スクリプト
   - IP 設定保持スクリプト
3. **ソース VM への変更はスクリプトコピーのみ**（ロールバック可能）

**Phase 2: 移行実行（Migrate）**

1. Blueprint 内の全 VM の既存スナップショットを削除
2. ソースで VM スナップショットをトリガー
3. ディスク変換前にボリュームスナップショットをトリガー
4. FlexClone で VMDK をターゲットフォーマットに変換
5. ターゲットホストで VM をパワーオン
6. 各 VM にネットワークを登録
7. VMware Tools を削除し、トリガースクリプト/cron ジョブで IP アドレスを割り当て

**Phase 3: 検証（Validate）**

- VM の正常起動確認
- データ整合性確認
- ネットワーク設定確認

> 出典: [Shift Toolkit Migration](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-migration.html)

### 2.6 前提条件

- VM は **NFS ボリューム上の ONTAP ストレージ**にホストされていること
- SAN（ブロック）ベースの ONTAP ストレージ上の VM は、事前に Storage vMotion で NFS データストアに移動が必要
- ONTAP 9.14.1 以降
- Shift Toolkit は Windows マシンにインストール
- 必要なポート: 443 (HTTPS: vCenter/ESXi/ONTAP/Target), 5985/5986 (WinRM: Hyper-V)
- 同時変換は同一ソース→デスティネーション間で **最大10並列**を推奨

### 2.7 制約事項と既知の制限

- Windows 専用ツール（Linux/Mac では動作しない）
- ソース VM は NFS データストア上に配置が必須
- CentOS/RHEL 5.x/6.x は非サポート
- Windows Server 2008 は公式非サポート（一部成功報告あり、IP 自動設定不可）
- KVM へのエンドツーエンド移行は未対応（ディスク変換のみ）
- EC2 への直接移行は **Early Preview** 段階（v8.0 で OS→EBS + Data→FSx for ONTAP の構成が確定）

### 2.8 Shift Toolkit v8.0 新機能（2026-06-19 リリース）

> 出典: [What's New in Shift v8.0](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)

**v7.0 からの追加機能（v7.0 recap）:**

- Proxmox VE エンドツーエンド移行サポート
- Proxmox 向けディスク変換
- ONTAP NAS Economy ドライバ対応（OpenShift: qtree サポート）
- 単一 NFS volume 上の複数 VM 対応（ONTAP NAS ドライバ）
- FlexGroup サポート（VMDK → RAW 変換のみ、KVM ハイパーバイザー向け）

**v8.0 新機能（すべて Preview）:**

| 機能 | ステータス | 概要 |
|------|-----------|------|
| **File-to-LUN Migration** | Preview | FlexVol volume 上のファイルをブロックレベル LUN（iSCSI）に直接変換。OpenShift Virtualization のブロックストレージ移行を高速化 |
| **EC2 + FSx for ONTAP** | Early Preview | OS ディスクを EBS 形式に変換（Import/Export APIs or Direct Access APIs）、データディスクを FSx for ONTAP に配置。SnapMirror による高速データ転送 |
| **Shift as Add-On for Trident** | Preview (v26.06) | Trident CSI プロビジョナーとの統合。OpenShift Virtualization でゼロコピーのコールドマイグレーションを実現 |

**EC2 Early Preview 有効化方法:**

- 連絡先: NetApp のサポート窓口（アドレスは Shift Toolkit v8.0 ブログに記載）
- ダウンロード: [MySupport Shift Toolkit ページ](https://mysupport.netapp.com/site/tools/tool-eula/netapp-shift-toolkit)

**EC2 移行パスの技術詳細（v8.0 ブログから確定）:**

```text
移行フロー:
1. ソース VM（ONTAP NFS データストア上）
2. SnapMirror でデータを FSx for ONTAP にレプリケーション
3. OS ディスク:
   - 方式 A: AWS Import/Export APIs → S3 経由 → EBS snapshot → AMI
   - 方式 B: Direct Access APIs → EBS snapshot 直接作成 → AMI
4. データディスク: FSx for ONTAP 上の iSCSI LUN として EC2 にアタッチ
5. EC2 インスタンス起動（AMI からブート + FSx for ONTAP iSCSI マウント）
```

---

## 3. VMware → EC2/FSx for ONTAP 移行アーキテクチャ

### 3.1 現在文書化されている移行方式（Cirrus Migrate Cloud）

NetApp 公式ドキュメントの「Migrate VMs to Amazon EC2」セクションでは、**Cirrus Migrate Cloud (CMC)** の MigrateOps 機能を使用した移行手順が文書化されている。

**アーキテクチャ概要:**

- ソース: VMware vSphere（オンプレミスまたは VMware Cloud on AWS）
- ターゲット:
  - OS ディスク → Amazon EBS（AMI としてブート）
  - データディスク → FSx for ONTAP（iSCSI LUN）
- 移行ツール: Cirrus Migrate Cloud + MigrateOps（YAML ベース自動化）

**CMC の特徴:**

- エージェントベースのブロックレベルレプリケーション
- ソース VM 稼働中にバックグラウンドで OS ディスクを bit-by-bit で移行
- 最終同期 + カットオーバーで短時間の停止のみ
- FSx for ONTAP の iSCSI LUN を自動プロビジョニング
- マルチパス/MPIO 設定を自動修正
- スナップショットによるロールバック保護

> 出典: [Migrate VMs to Amazon EC2 - Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-overview.html)

### 3.2 Shift Toolkit EC2 Early Preview の位置づけ

今回の Early Preview では、VMware ESXi から AWS EC2 への移行において、**OS ディスクを EBS 形式に変換し、データディスクを Amazon FSx for NetApp ONTAP 上に配置する**アプローチが対象です。これは、VMware ワークロードの移行先をオンプレミスの別ハイパーバイザーだけでなく、AWS 上の Amazon EC2 へ広げる可能性を持つ取り組みです。

> 🆕 **2026-06-22 更新（公式手順書で全容確定）**: EC2 移行パスの詳細手順書「Migrate VMs from VMware to AWS EC2 and FSx for ONTAP — Shift UI」を入手。OS → EBS → AMI のエンドツーエンドフロー、ゲスト OS 準備（cloud-init/ENA/EC2Launch）、SnapMirror break → LUN 変換 → iSCSI アタッチの全工程が明確化された。
> 先行情報: [What's New in Shift v8.0 ブログ（2026-06-19）](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)

**Early Preview の確定範囲（公式手順書に基づく）:**

- OS ディスク → **EBS 形式に変換**（2つの方式を提供）
  - **Amazon EBS Direct APIs**（推奨・最速）: EBS snapshot を直接作成。リージョン/AZ/アカウント横断対応
  - **AWS VM Import/Export**: VMDK → RAW → S3 アップロード → AMI 変換
  - **現在の Preview**: S3 import/export のみ有効。EBS Direct APIs は次回ドロップで有効化
- データディスク → FSx for ONTAP 上の **iSCSI LUN** に VMDK → LUN 変換
- SnapMirror レプリケーションを活用した高速データ転送（事前設定必須）
- 移行後は FSx for ONTAP のネイティブ LUN として Snapshot / SnapMirror / FlexClone がすべて利用可能
- ゲスト OS 準備: cloud-init（Linux）/ EC2Launch v2（Windows）を自動注入
- 利用には NetApp のサポート窓口への連絡と config.json 編集（`enableAmazonEC2: true`）が必要

**確定した構成:**

```text
OS / ルートディスク  → Amazon EBS (gp3)        ← VMDK→RAW→S3→AMI（現 Preview）
                                                 or VMDK→EBS Direct API（次回ドロップ）
データディスク       → FSx for ONTAP (iSCSI LUN) ← VMDK→LUN 変換 + igroup マッピング
```

**確定した移行フロー（ハイレベル）:**

```text
1. [事前] SnapMirror: ソース ONTAP NFS volume → FSx for ONTAP にレプリケーション
2. [事前] VM を graceful shutdown（計画メンテナンス）
3. VMware snapshot 削除 → 新規 snapshot → ONTAP volume snapshot
4. SnapMirror update（最終差分転送）
5. SnapMirror break（FSx for ONTAP 側が R/W に）
6. Boot disk: VMDK → RAW 変換 → S3 アップロード → AMI 登録
7. Data disk: VMDK → LUN 変換（FSx for ONTAP 上）
8. iSCSI ターゲット準備: igroup 作成、LUN マッピング、IQN 検出
9. EC2 インスタンス起動（AMI からブート）
10. EC2 ゲスト内で iSCSI 接続 → データディスクマウント
```

**前提条件サマリー:**

| カテゴリ | 要件 |
|---------|------|
| VM 配置 | NFSv3 データストア上（同一ボリュームに全 VMDK） |
| VMware Tools | ゲスト VM で稼働中（準備フェーズで必要） |
| SnapMirror | ソース NFS volume → FSx for ONTAP 間で健全な状態 |
| ネットワーク | オンプレミス ↔ AWS VPC 間の接続（DX or VPN） |
| FSx for ONTAP | 指定 VPC 内にプロビジョニング済み |
| IAM | vmimport ロール + SSM インスタンスプロファイル |
| セキュリティグループ | iSCSI(3260), HTTPS(443), SSH(22), RDP(3389), WinRM(5985-5986), SnapMirror(11104-11105) |
| S3 バケット | VM Import/Export 用のステージングバケット |

**注意**: Early Preview の有効化については NetApp のサポート窓口に連絡する（アドレスは Shift Toolkit v8.0 ブログに記載）。Shift Toolkit のインストールディレクトリ `config.json` で `enableAmazonEC2` を `true` に変更し、NetApp Shift サービスを再起動する。

**詳細な移行手順書**: [`docs/ja/shift-toolkit-ec2-procedure.md`](./shift-toolkit-ec2-procedure.md)

### 3.2.1 OS ディスクのブート方式 — ✅ 全解決（公式手順書で確定）

> 🆕 **2026-06-22 更新**: 公式手順書により Q1–Q4 すべて解決。本セクションは完了。

EC2 インスタンスは Amazon Machine Image (AMI) からブートする必要があり、VMDK を直接マウントして起動することはできない。→ **公式手順書で確定**: Shift Toolkit 自身が OS ディスクを EBS 形式に変換し AMI を登録する。

**確定した EBS 変換方式（2つ）:**

| 方式 | 概要 | ステータス | 用途 |
|------|------|-----------|------|
| AWS VM Import/Export | VMDK → RAW → S3 → `import-image` → AMI | ✅ 現 Preview で有効 | 標準変換パス |
| Amazon EBS Direct APIs | EBS snapshot 直接作成（推奨・最速）、リージョン/AZ/アカウント横断 | 🔜 次回ドロップで有効化 | 高速・大容量向け |

**ゲスト OS 準備（自動化確定）:**

| OS | 自動注入される内容 | 手動対応 |
|----|-------------------|---------|
| Ubuntu/Debian | cloud-init + EC2 datasource + Chrony | prepareVM 無効時はコマンド手動実行 |
| SUSE/openSUSE | cloud-init + growpart + Chrony | 同上 |
| Windows | EC2Launch v2（MSI サイレント） | 同上 |

**注**: 現 Preview 版では `prepareVM` フェーズが disabled。次回ビルドで自動化有効。それまではドキュメント記載の手動コマンドで対応可能。

**全質問の最終ステータス:**

| # | 質問 | ステータス |
|---|------|-----------|
| Q1 | OS の AMI 変換含むか? | ✅ 含む（エンドツーエンド） |
| Q2 | 別ツール併用必要? | ✅ 不要（VM Import/Export は内部利用） |
| Q3 | AMI 作成の標準手順? | ✅ 自動化（VMDK→RAW→S3→AMI） |
| Q4 | ドライバ自動化? | ✅ 自動化（cloud-init/EC2Launch/ENA） |

### 3.2.2 移行ツール選択ガイダンス

顧客が VMware → EC2 移行ツールを選択する際の判断基準:

```text
┌─────────────────────────────────────────────────────────────┐
│ VMware → EC2 移行ツール選択フローチャート                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Q: 現在 ONTAP NFS データストアを使用しているか?             │
│  ├─ No → AWS MGN（標準、無償、幅広い OS 対応）              │
│  │                                                         │
│  └─ Yes                                                    │
│       Q: データディスクを FSx for ONTAP に配置したいか?          │
│       ├─ No → AWS MGN（EBS のみ構成）                      │
│       │                                                     │
│       └─ Yes                                                │
│            Q: 移行規模は?                                    │
│            ├─ 大規模 (100+ VM) → CMC MigrateOps            │
│            │   - エンタープライズサポート必要                 │
│            │   - ゼロダウンタイム要件あり                     │
│            │   - YAML 自動化で大量並列処理                   │
│            │                                                 │
│            └─ 中小規模 / PoC → Shift Toolkit (Early Preview)│
│                - ONTAP FlexClone で高速変換                  │
│                - 無償、GUI 操作                              │
│                - ONTAP 運用モデル継続が目的                  │
│                                                             │
│  補助ツール / オーケストレーション:                          │
│  - AWS Transform: discovery〜計画〜コンピュート/NW/ストレージ │
│    を一気通貫。FSx for ONTAP 宛先は Public Preview。詳細は 3.2.3 参照  │
│  - BlueXP Migration Advisor: 計画・サイジング（どのパスでも） │ <!-- allow:naming -->
│  - VM Import/Export: OS ディスクの AMI 化（必要に応じて）     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

> **2026-06 追記**: AWS Transform が FSx for ONTAP を移行先としてサポート（Public Preview）。
> 上記フローは「移行エンジン」の選択軸。AWS Transform は「オーケストレーション層」であり、
> 排他選択ではなく上位レイヤーで併用しうる。使い分けは 3.2.3 を参照。

**判断軸の詳細:**

| 判断軸 | MGN を選ぶ場合 | Shift Toolkit を選ぶ場合 | CMC を選ぶ場合 |
|--------|--------------|------------------------|---------------|
| ストレージ前提 | ONTAP 不使用 or EBS のみで十分 | ONTAP NFS データストア使用中 | ONTAP 使用中 + 大規模 |
| FSx for ONTAP 利用意向 | なし | データディスクを FSx for ONTAP に配置 | データ + 一部 OS も FSx for ONTAP |
| 移行規模 | 任意 | 中小規模 / PoC | 100+ VM |
| ダウンタイム許容 | 短い停止可 | 計画停止可（FlexClone は秒） | ゼロダウンタイムに近い |
| コスト | 無償 | 無償 | 有償（Marketplace） |
| サポート | AWS 標準 | NetApp Community | Cirrus 商用 |
| ONTAP 運用継続 | 不要 | 必要（主目的） | 必要 |
| AWS 標準サポート | 必要 | 不要 | 不要 |

### 3.2.3 AWS Transform との使い分け（2026-06 Public Preview）

2026-06-16 付で **AWS Transform for migrations が Amazon FSx for NetApp ONTAP を移行先としてサポート**（Public Preview）した。[（出典）](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/) これにより、従来 Amazon EBS のみだったブロックストレージの移行先に FSx for ONTAP が加わり、コンピュート・ネットワークと同一の移行ウェーブ内でブロックデータを FSx for ONTAP ボリュームへ直接レプリケートできるようになった。

**本質的な位置づけ**: AWS Transform は「移行ウェーブ全体を回す AWS ネイティブのオーケストレーター」、Shift Toolkit は「ONTAP 上の VM を高速変換する NetApp ネイティブのエンジン」。レイヤーが異なり、排他的に選ぶものではない。v8.0 ブログ + 公式手順書により、**Shift Toolkit も OS→EBS + Data→FSx for ONTAP をエンドツーエンドでカバーする**ことが確定（3.2.1 で解決済み）。両者とも単体で完結できるが、アプローチと適性が異なる。

| 観点 | AWS Transform (Public Preview) | Shift Toolkit (本検証対象 / Early Preview) |
|------|------|------|
| 提供元 / 性質 | AWS / エージェント型 AI の移行オーケストレーション | NetApp / FlexClone ベースの変換ツール |
| カバー範囲 | discovery → 計画 → コンピュート + ネットワーク + ストレージを同一ウェーブで | OS→EBS + データ→FSx for ONTAP LUN のエンドツーエンド。計画・NW は別 |
| ソース前提 | ソース非依存（オンプレ / 他クラウド / VMware のブロック・NFS データストア） | ソース VM が ONTAP NFSv3 データストア上にあることが必須 |
| FSx for ONTAP の位置づけ | ブロックストレージの移行先（EBS に加えて選択可。直接レプリケート） | データディスクの配置先（VMDK → iSCSI LUN 変換） |
| 変換の仕組み | AWS ネイティブのブロックレプリケーション（MGN agent-based 継続同期） | SnapMirror + ONTAP FlexClone（ゼロデータコピー、秒〜分） |
| NetApp 連携点 | discovery が NetApp DII 取り込みに対応（計画フェーズでの連携） | ツール自体が ONTAP / FlexClone / SnapMirror 前提 |
| OS / ルートディスク | MGN がコンピュート移行として EBS ブートを自動処理 | VMDK→RAW→S3→AMI（現 Preview）。EBS Direct APIs（次回ドロップ） |
| ダウンタイム特性 | 継続レプリ → 短時間カットオーバー（分レベルと想定） | 計画停止 30分〜2.5時間（S3 upload + import-image が支配的） |
| マルチアカウント対応 | あり（Connector + MGN cross-account 初期化） | なし（単一 AWS アカウント指定） |
| AI / 自動化 | AI 駆動（ウェーブ提案、NW 変換、インスタンスタイプ推奨） | GUI ベース（Blueprint 手動作成。REST API あり） |
| コスト / 提供 | VMware 移行は無料。移行先 AWS インフラは通常課金 | 無償。移行先 AWS インフラは通常課金 |
| 成熟度 | GA（基本機能）+ FSx for ONTAP 宛先は Public Preview | Early Preview（v8.0 で EC2 パス公式化） |

> **接点の理解**: 現時点で確認できる AWS Transform と Shift Toolkit の接点は、discovery の **NetApp DII 取り込み**（＝計画フェーズの連携）に見える。AWS Transform が移行エンジンとして FlexClone を使うわけではなさそうだが、ここは NetApp への要確認事項（3.2.4 A1/A2）。

#### ルートボリュームの扱い（両ソリューション共通の物理制約）

EC2 は **AMI（EBS バックド）からしかブートできず、FSx for ONTAP の iSCSI LUN から直接起動はできない**。したがって構成は両方とも次に収束する。

```text
OS / ルートディスク  → Amazon EBS (gp3)      ← ブート要件（不可避）
データディスク       → FSx for ONTAP (iSCSI)  ← ONTAP 機能を継続
```

違いは「ルートディスクを誰が EBS 化するか」:

- **Shift Toolkit**: v8.0 で OS ディスクの EBS 変換を自身がカバーすることが確定。AWS Import/Export APIs または Direct Access APIs の 2 方式を提供。（[出典: v8.0 ブログ](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)）
- **AWS Transform**: コンピュート移行を含むため、OS ディスクの EBS ブート化（AMI 化・Nitro ドライバ注入等）をサービス側で吸収すると考えられる（要確認）。

→ ルートボリュームはどちらも **EBS** が基本。~~Shift Toolkit で別ツール併用が要る部分を~~ v8.0 で Shift 自身が EBS 化をカバーしたため、両ツールとも**単体で OS + Data を完結できる**方向に収束した。

#### 使い分けガイダンス

- **AWS ネイティブの一気通貫・大規模計画・ソースが ONTAP 以外も混在** → AWS Transform。discovery〜コンピュート〜ネットワーク〜ストレージを 1 フローで回せる。NetApp DII があれば計画精度も上がる。
- **すでにオンプレ ONTAP NFS データストアで運用中・FlexClone の変換速度と ONTAP 運用継続が主目的・中小規模 / PoC** → Shift Toolkit。秒単位の変換とゼロデータコピーが効く。
- **両取り**: AWS Transform で計画・コンピュート・ネットワークを回し、データの最終ランディングを FSx for ONTAP にする組み合わせも論理的に成立。ただし「AWS Transform の FSx for ONTAP 移行が SnapMirror / FlexClone を使うのか、AWS ネイティブコピーなのか」で移行後の ONTAP 運用継続性（Snapshot 系譜の引き継ぎ等）が変わるため、ここが分かれ目。

#### サポートOSの観点 — レガシーOSの壁（2026-06 時点）

VMware → EC2 のリホストで現場が最もつまずくのは新しい OS ではなく、**古い / EOL のゲスト OS** である。AWS Transform のリホスト実体は **AWS Transform MGN（旧 AWS Application Migration Service）** であり、サポート OS には明確なマトリクスがある。

**AWS Transform MGN サポートOS（抜粋）** [（出典）](https://docs.aws.amazon.com/mgn/latest/ug/Supported-Operating-Systems.html)

| 区分 | 現行サポート | 終息 / 非対応（レガシー） |
|------|------------|------------------------|
| Windows | Server 2016 / 2019 / 2022 / 2025、Windows 10 / 11（いずれも 64bit） | Server 2003（2026-02-15 終了）、Server 2008・Windows 7（2026-12-30 終了）、Server 2012（EOL 表記） |
| Linux | RHEL 6.0〜9.7 / 10 / 10.1、CentOS 6.0〜8.0・Stream 9 / 10、Amazon Linux 1 / 2 / 2023 | RHEL/CentOS 5.x（2025-12-30 終了済）、CentOS 6.x（2026-08-28）、RHEL 6.x / CentOS 8.x（2026-12-30）、CentOS 7（2026-11-20）、Amazon Linux 1（2026-11-20） |
| アーキ | x86_64（64bit） | **32bit Linux は非対応**、カーネル 2.6.18-164 未満は非対応、カーネル 4.9.256 非対応 |

**補助ツール VM Import/Export** [（出典）](https://docs.aws.amazon.com/vm-import/latest/userguide/prerequisites.html)

- 2026-04-01 で **i386（32bit）サポートを終了**（Windows Server 2003/2008、RHEL/CentOS 5・6、各種 Ubuntu 32bit 等）
- EOL OS は動作検証対象外（強く非推奨）

> **検証者の観点**: 「古い資産ほど個別対応になりがち」が実情。ただし **Shift Toolkit 側にも OS 制約**があり（RHEL 7.2+ / 8 / 9、CentOS 7、Windows Server 2016+ 等。CentOS/RHEL 5.x/6.x は非対応、本レポート 2.3 参照）、「Shift Toolkit ならレガシーを解決できる」という主張はできない。本質的な打ち手は **OS 起動（AMI/EBS、OS サポートマトリクスに依存）とデータ層（FSx for ONTAP、ONTAP 機能継続）を分離して設計する**こと。レガシー OS で起動変換が困難でも、データを FSx for ONTAP に寄せておけば「データのモダナイズ」と「OS の延命/再構築」を切り離して判断できる。これが本検証で確かめる仮説の一つ。

> ⚠️ 上記 OS バージョン・EOL 日付は **2026-06 時点**の一次情報。AWS により随時更新されるため、引用時は取得日を明記し、最新ドキュメントで再確認すること。

#### コスト構造（AWS Transform / 2026-06 時点）

AWS Transform の料金は「サービス（エージェント）」と「生成される AWS インフラ」を明確に分けて理解する必要がある。[（出典）](https://aws.amazon.com/transform/pricing/)

| 区分 | 料金 |
|------|------|
| Assessment / Windows / Mainframe / **VMware 移行**エージェント | **無料** |
| Custom transformation エージェント（コード/API/フレームワーク変換） | **有料**: $0.035 / agent-minute（最小1分単位、能動的な計画・解析・変更時間のみ課金。ローカルビルド/アイドルは対象外） |
| 移行先 AWS インフラ（EC2 / EBS / **FSx for ONTAP** / データ転送 / NAT・VPC エンドポイント等） | **通常料金で別途課金** |

> **検証者の観点**: VMware → EC2/FSx for ONTAP 移行では **AWS Transform のサービス利用自体は無料**であり、実コストの中心は移行先インフラ（特に EC2 + EBS ルート + FSx for ONTAP）。Shift Toolkit も「無償ツール + インフラ実費」という同じ構造で、**両者ともツール費よりインフラ設計（FSx for ONTAP サイジング・Storage Efficiency）がコストを左右する**。本検証の FinOps 観点（6章 Phase 3d）と整合させ、「サービス無料」を「移行全体が無料」と誤認させない説明が必要。

#### 3.2.4 AWS Transform リリースを受けた NetApp 確認事項（既存 Q1–Q4 に追加）

**A. AWS Transform と Shift Toolkit の関係**

| # | 質問 | 影響度 |
|---|------|--------|
| A1 | AWS Transform の FSx for ONTAP 移行は内部で Shift Toolkit / FlexClone / SnapMirror を使うのか、AWS ネイティブのブロックレプリケーションか? | Critical |
| A2 | NetApp DII 連携は discovery のみか、移行実行フェーズにも及ぶか? | High |
| A3 | NetApp として顧客に Shift Toolkit と AWS Transform をどう使い分け案内する想定か（置き換え / 補完 / 並存）? | High |

**B. ルート / OS ディスク（✅ P0 解決済み）**

| # | 質問 | 影響度 | ステータス |
|---|------|--------|-----------|
| B1 | ~~Shift Toolkit Early Preview は OS ディスクの AMI 化まで含むか、データディスクのみか?~~ | ~~Critical~~ | ✅ 解決: v8.0 で OS ディスクの EBS 変換を含むことが確定 |
| B2 | ~~含まない場合~~ AWS Transform と Shift Toolkit の OS/Data 分担は? | ~~High~~ → Low | ✅ 整理済み: Shift 自身が OS→EBS を処理。AWS Transform との分担は「排他」ではなく「選択肢」 |

**C. FSx for ONTAP 移行先としての仕様**

| # | 質問 | 影響度 |
|---|------|--------|
| C1 | AWS Transform の FSx for ONTAP 移行先はブロック（iSCSI LUN）のみか、NFS データストア相当も対象か? | High |
| C2 | 移行後に Snapshot / SnapMirror / FlexClone / Storage Efficiency はそのまま継続利用できるか（系譜・メタデータの引き継ぎ有無）? | Critical |
| C3 | 対応リージョン（東京 ap-northeast-1 で Preview 利用可否）と Preview の制約・GA 時期は? | Medium |

> ⚠️ **distinction discipline**: 上表のうち「AWS ネイティブの仕組み」「ルートの EBS 化を自動吸収」はリリースノートからの**推定**であり、一次情報での確認が必要。Public Preview のため GA 仕様・対応リージョン・制約は確定情報として扱わない。

### 3.3 EC2 + FSx for ONTAP 構成パターン

**推奨構成:**

```text
┌─────────────────────────────────────┐
│          Amazon EC2 Instance         │
├─────────────────────────────────────┤
│  OS Disk: Amazon EBS (gp3)          │
│  Data Disk: FSx for ONTAP (iSCSI)   │
└──────────────┬──────────────────────┘
               │ iSCSI
┌──────────────▼──────────────────────┐
│     FSx for NetApp ONTAP            │
│  - Multi-AZ / Single-AZ            │
│  - iSCSI LUN for data              │
│  - Snapshot / FlexClone             │
│  - SnapMirror (DR)                  │
│  - Storage Efficiency               │
└─────────────────────────────────────┘
```

**BlueXP Workload Factory Migration Advisor のストレージ戦略:** <!-- allow:naming -->

- **OS ボリューム**: EBS gp3（EC2 ブート要件）
- **データボリューム**: FSx for ONTAP iSCSI LUN
  - Performance-optimized: 高 IOPS 要件
  - Standard: 汎用（autotiering 有効）
  - Capacity-optimized: アーカイブ/低アクセス

> 出典: [AWS Storage Blog - BlueXP Migration Advisor](https://aws.amazon.com/blogs/storage/expedite-vmware-migration-to-amazon-ec2-and-amazon-fsx-for-netapp-ontap-using-bluexp-workload-factory-for-aws-migration-advisor/) <!-- allow:naming -->

---

## 4. 3者への価値整理

### 4.1 AWS ユーザー向け

AWS ユーザーにとっての価値は、VMware ワークロードを Amazon EC2 と FSx for ONTAP の組み合わせへ移行することで、AWS の柔軟性と ONTAP のデータ管理機能を同時に活用できる点にあります。

Amazon FSx for NetApp ONTAP は、AWS 上でフルマネージドの ONTAP ファイルシステムを提供し、NFS、SMB、iSCSI からアクセスできる高性能ストレージとして説明されています。さらに、Snapshot、clone、replication、compression、deduplication などの機能を備え、EC2、ECS、EKS、VMware Cloud on AWS、WorkSpaces、AppStream 2.0 などの AWS コンピュートサービスから利用できるとされています。[（出典）](https://aws.amazon.com/documentation-overview/netapp-ontap/)

AWS Storage Blog では、VMware から Amazon EC2 と FSx for ONTAP への移行について、オンプレミスまたはクラウド上の VMware 環境から既存 VM とストレージを Amazon EC2、Amazon EBS、Amazon FSx for NetApp ONTAP の組み合わせへ移行する自動化ソリューションとして紹介されています。移行プロセスはカットオーバー時の短い停止までは非破壊的に進められ、移行元のブロックデバイス種別にも柔軟に対応できると説明されています。[（出典）](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/)

**AWS ユーザー向けの要点:**

| 価値 | 説明 | 根拠 |
|------|------|------|
| 新しい移行パス | VMware → EC2 + FSx for ONTAP。データディスクを FSx for ONTAP に配置する構成 | [AWS Storage Blog (2024/10)](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/) |
| スケーラビリティ + データ管理 | EC2 のコンピュート弾力性 + ONTAP のエンタープライズストレージ機能 | FSx for ONTAP は VM レベルの I/O 制限なし（ネットワーク帯域のみ） |
| コスト最適化 | EBS のみ vs EBS + FSx for ONTAP ハイブリッド。FSx for ONTAP の thin provisioning、dedup、compression で実効容量削減 | BlueXP Migration Advisor がコスト比較を自動生成 | <!-- allow:naming -->
| VMware Migration Accelerator | 移行 VM あたり最大 $400 USD クレジット | [AWS VMware Migration Accelerator](https://aws.amazon.com/vmware/migrationaccelerator/) |
| 小型インスタンスでの高性能 | FSx for ONTAP は network bandwidth limits のみ → 小さい EC2 で高 IOPS 実現 | FSx for ONTAP で最大 ~350K IOPS（※条件付き: Flash Cache 有効、複数 iSCSI セッション、ワーキングセットサイズ 5% 以下の場合。[出典: NetApp Solutions](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-overview.html)。本検証で実測予定） |

> **検証者の観点**: これは単なる VM の置き換えではなく、VMware ベースの既存資産を AWS 上で再配置し、将来的には AWS ネイティブサービスとの連携、運用自動化、DR、データ活用へ広げていくための入口になると考えています。

### 4.2 NetApp ユーザー向け

NetApp ユーザーにとっての価値は、ONTAP で培ったデータ管理・効率化・保護の考え方を、AWS 上の FSx for ONTAP に拡張できる点です。

AWS の FSx for ONTAP ドキュメントでは、FSx for ONTAP は ONTAP の familiar features、performance、capabilities、APIs を AWS のマネージドサービスとして提供するものと説明されています。SnapMirror replication によるオンプレミス ONTAP から AWS への効率的な移行をサポートし、FlexClone による point-in-time clone も利用できるとされています。[（出典）](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/how-it-works-fsx-ontap.html)

Shift Toolkit 側でも、NetApp は ONTAP の FlexClone 技術を活用して VM ハードディスクを高速に変換すると説明しており、NetApp Blog では、データをコピーせずに VM を変換することで、プロジェクト期間を大幅に短縮し、変換時間を数時間・数日から数分へ短縮できると紹介されています。[（出典1）](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html) [（出典2）](https://www.netapp.com/blog/simplify-vm-migration-shift-toolkit/)

**NetApp ユーザー向けの要点:**

| 価値 | 説明 | 根拠 |
|------|------|------|
| ONTAP 運用モデルの継続 | Snapshot、FlexClone、SnapMirror、Storage Efficiency が AWS でそのまま利用可能 | FSx for ONTAP は完全マネージドの ONTAP ファイルシステム |
| FlexClone による移行加速 | 1TB VMDK の変換が数秒〜数分。データコピー不要 | [Shift Toolkit Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html) |
| SnapMirror によるデータ転送 | オンプレ ONTAP → FSx for ONTAP へのブロックレベルレプリケーション | [Migrate VMs to EC2 - Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-overview.html) |
| iSCSI LUN の継続利用 | オンプレで使用していた iSCSI ベースのワークロードを FSx for ONTAP で継続 | マルチプロトコル対応（NFS/SMB/iSCSI） |
| 既存スキルの活用 | ONTAP CLI/API、SnapCenter、SnapMirror の運用知識がそのまま活かせる | FSx for ONTAP は ONTAP API 互換 |

> **検証者の観点**: これは「ONTAP を持っているから移行できる」だけではなく、「ONTAP の運用モデルを AWS でも活かせる」ことが重要です。Shift Toolkit が ONTAP / FlexClone の特性を活かして VM 移行やディスク変換を高速化することで、NetApp ストレージは単なる保存先ではなく、移行そのものを加速するプラットフォームになります。

### 4.3 VMware ユーザー向け

VMware ユーザーにとっての価値は、既存の VMware ワークロードを維持し続けるか、別ハイパーバイザーへ移すか、AWS の EC2 へ移行するかという選択肢を増やせる点です。

NetApp のドキュメントでは、近年の市場変化を背景に、多くの組織が技術的・商業的リスクを比較しながら、ワークロード VM を代替ハイパーバイザーへ移行する選択肢を検討していると説明されています。[（出典）](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)

AWS Storage Blog でも、Broadcom による VMware 買収後、VMware の販売・ライセンスモデルに変化があり、多くの企業が仮想化戦略を見直し、Amazon EC2 への効率的な移行パスを探していると説明されています。[（出典1）](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/) [（出典2）](https://aws.amazon.com/blogs/storage/expedite-vmware-migration-to-amazon-ec2-and-amazon-fsx-for-netapp-ontap-using-bluexp-workload-factory-for-aws-migration-advisor/)

**VMware ユーザー向けの要点:**

| 価値 | 説明 | 根拠 |
|------|------|------|
| 移行先選択肢の拡大 | Hyper-V, OpenShift, Proxmox, OLVM, EC2 と多様な選択肢 | [Shift Toolkit Supported Migrations](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-migration.html) |
| Broadcom ライセンス対策 | ライセンス変更に対する戦略的選択肢としてのマルチハイパーバイザー戦略 | [NetApp Blog](https://www.netapp.com/blog/simplify-vm-migration-shift-toolkit/) |
| 段階的移行の現実性 | 一部 VM を EC2 へ、残りは既存維持。ソース VM は変更されないためロールバック容易 | Shift Toolkit はソース VM にスクリプトコピーのみ実施 |
| ダウンタイム最小化 | FlexClone ベースの変換は数秒。計画停止ウィンドウを最小化 | プロジェクト期間を最大 70% 短縮した事例あり |
| コスト削減 | コンサルティング費用、サードパーティツール費用、デュアルライセンス期間の排除 | NetApp Blog: ツール無償提供 |

> **検証者の観点**: Shift Toolkit は「今すぐ VMware をやめるためのツール」というよりも、「VMware ワークロードの将来の配置先を増やすためのツール」と捉えるのが自然だと考えています。特に VMware to EC2 / FSx for ONTAP のプレビューは、VMware の VM を AWS 上の EC2 に移し、データディスクを FSx for ONTAP に配置するという構成を検証できる点で、オンプレミス VMware から AWS への移行パスを具体化する材料になります。

### 4.4 3者をつなぐメッセージ

Shift Toolkit の価値は、AWS、NetApp、VMware のいずれか一社の視点だけでは語りきれません。

- **AWS ユーザー**にとっては、VMware ワークロードを Amazon EC2 と FSx for ONTAP に移行することで、AWS のスケーラビリティ、運用自動化、クラウドネイティブサービスへの接続性を得る機会になります。
- **NetApp ユーザー**にとっては、ONTAP の Snapshot、FlexClone、SnapMirror、storage efficiency といったデータ管理の強みを、AWS 上の FSx for ONTAP でも活かせる機会になります。
- **VMware ユーザー**にとっては、既存の VM 資産を活かしながら、移行先の選択肢を増やし、ライセンス、運用、将来のクラウド戦略を見直すきっかけになります。

私はこの検証を通じて、VMware から AWS への移行を「単なるリホスト」ではなく、**「ONTAP のデータ管理を活かした AWS 上での再設計」**として整理していきたいと考えています。

---

## 5. 移行ツールの比較と選択ガイド

### 5.0 顧客の最初の質問（Partner/SI 観点）

パートナー/SI がこの検証結果を使って顧客と対話する際の**起点となる質問**:

> **「VMware の次をどうするか決めていますか? 今使っているストレージの種類によって、最適な移行パスが変わります。」**

この質問から始まるデシジョンフロー:

1. 現在のストレージは ONTAP か? → Yes: Shift Toolkit / CMC が候補。No: MGN が候補
2. データディスクの ONTAP 機能（Snapshot, Clone, DR）を AWS でも使い続けたいか? → Yes: FSx for ONTAP + Shift Toolkit
3. 移行規模は? → 大規模: CMC。中小規模/PoC: Shift Toolkit
4. いつ移行したいか? → 今すぐ（GA ツールのみ）: MGN or CMC。将来計画: Shift Toolkit Early Preview を先行検証

**パートナーが顧客に提供できる成果物（本検証から生成）:**

- ツール選択フローチャート（セクション 3.2.2）
- ツール比較表（セクション 5.1）
- コスト比較レポート（Phase 3d の結果）
- PoC 実行計画テンプレート（Phase 1-3 を簡略化したもの）

| ツール | 提供元 | アプローチ | FSx for ONTAP 対応 | OS ディスク先 | データディスク先 | 特徴 | 適用シナリオ |
|--------|--------|-----------|-----------|-------------|--------------|------|------------|
| **Shift Toolkit** | NetApp | ONTAP FlexClone + ディスク変換 | ✅ (OS→EBS + Data→FSx for ONTAP・Early Preview) | EBS (確定: Import/Export API or Direct Access API) | FSx for ONTAP iSCSI | ONTAP 顧客向け、数秒での変換、無償 | ONTAP NFS データストア利用中の環境 |
| **Cirrus Migrate Cloud (CMC)** | Cirrus Data Solutions | エージェントベース・ブロックレプリケーション | ✅ (iSCSI LUN 自動構成) | EBS | FSx for ONTAP / EBS | YAML ベース自動化 (MigrateOps)、VM 稼働中に移行 | 大規模エンタープライズ移行 |
| **AWS MGN (Application Migration Service)** | AWS | エージェントベース・継続レプリケーション | ❌ (EBS のみ) | EBS | EBS | AWS 標準ツール、幅広い OS 対応、無償 | 汎用的な Lift & Shift |
| **BlueXP Workload Factory Migration Advisor** | NetApp/AWS | 計画 + 最適化 + 自動デプロイ | ✅ (計画・ストレージ最適化) | EBS gp3 | FSx for ONTAP iSCSI | RVTools/PowerCLI 連携、コスト比較、IaC 出力 | 移行計画・サイジング | <!-- allow:naming -->
| **VMware HCX** | VMware/Broadcom | ライブマイグレーション | ❌ (VMC on AWS 専用) | VMFS/vSAN | VMFS/vSAN | VMC 専用、vMotion ベース、ライブ移行 | VMC on AWS への移行 |
| **AWS VM Import/Export** | AWS | VMDK/VHD/OVA → AMI 変換 | ❌ | EBS | EBS | AWS 標準、バッチ処理向き | 小規模・手動移行 |
| **AWS Transform** | AWS | エージェント型 AI オーケストレーション（discovery→計画→移行） | ✅ (ブロック宛先・Public Preview) | EBS | FSx for ONTAP / EBS | 移行ウェーブ一括（compute+NW+storage）。VMware移行は無料、discovery が NetApp DII 対応 | AWS ネイティブ一気通貫・大規模計画・ソース混在 |

### 5.1 Shift Toolkit の特徴と適した場面

1. **データコピー不要（Zero Data Copy）**: FlexClone により物理データの移動なしでディスク変換。データコピー/レプリケーションを伴うアプローチに比べ、転送量と所要時間を抑えられる
2. **変換速度**: 1TB あたり数秒〜数分（データコピー方式では同規模で数時間〜数日を要する場合がある）
3. **提供形態**: NetApp から無償で提供。提供形態（有償/無償）や FSx for ONTAP 対応の有無は選択肢ごとに異なる（セクション 5.0 の表を参照）
4. **ONTAP エコシステム統合**: 既存の ONTAP ストレージ上の VM をそのまま活用。追加のストレージリソース不要
5. **ソース VM 非破壊**: ソース VM にはスクリプトコピーのみ。失敗時のロールバックが即座に可能

**適用上の前提・制約（特性の裏返し）:**

- ONTAP NFS データストアが前提（非 ONTAP 環境では使えない）
- Windows 専用ツール
- EC2 対応は Early Preview（v8.0 で OS→EBS + Data→FSx for ONTAP が確定。GA 時期未定）
- EC2 Early Preview 有効化には NetApp のサポート窓口への連絡が必要

---

## 6. 検証計画（Phase 1-4）

### 6.0 検証の成功指標（検証開始前に定義）

この検証は、VMware 顧客が EC2 + FSx for ONTAP へ移行する際の**意思決定材料を提供する**ことをゴールとする。「Shift Toolkit で移行できた」だけでは成功ではなく、以下の指標を満たすことで「顧客が判断できる状態」を達成する。

| # | 成功指標 | 目標値 | 測定方法 | 対応ブログ記事 |
|---|---------|--------|---------|-------------|
| S1 | データディスク変換時間 | FlexClone 活用で 100GB あたり 5分以内（データコピーを伴う方式は転送時間が支配的になるのに対し、FlexClone は変換時間を最小化できることを実測で確認） | Shift Toolkit ジョブログのタイムスタンプ | #2, #4, #5 |
| S2 | カットオーバー停止時間 | 全体プロセスの停止時間を実測し記録。目標: 30分以内（小規模 VM） | VM 停止〜EC2 起動完了の時刻差分 | #4, #5 |
| S3 | データ整合性 | 100% 一致（ゼロ差分） | 移行前後の sha256sum 全ファイル比較 | #4, #5 |
| S4 | FSx for ONTAP iSCSI パフォーマンス | ベースラインとの比較レポート作成。同一 FSx for ONTAP 構成内で ±10% の再現性 | fio (4K random R/W, 64K sequential R/W) — パラメータ詳細は Phase 3c 参照 | #6 |
| S5 | ONTAP 機能動作確認 | Snapshot/Clone/Efficiency の全項目 PASS | ONTAP CLI 実行結果のエビデンス | #7 |
| S6 | コスト比較 | EBS のみ構成との月額コスト差を算出。Storage Efficiency 反映後の実効コストも提示 | AWS Pricing Calculator + 実測データ | #8 |
| S7 | 手順の再現性 | 第三者が手順書のみで再現可能 | 検証者以外による再実行テスト（可能であれば） | 全記事 |

> **注意**: S1 の「5分以内」は FlexClone ベース変換の期待値であり、ネットワーク転送（SnapMirror 初期転送）の時間は含まない。FlexClone 変換自体は公式ドキュメントで「数秒〜数分」と記載されているが、Early Preview での実測で確認する。S4 の fio パラメータセットとベンチマーク実行条件は Phase 3c に定義する。

**検証の安全なガードレール（Early Preview で何をやってよいか）:**

| やってよいこと | やってはいけないこと |
|-------------|-----------------|
| テストデータ（ダミー）でのディスク変換テスト | 本番データでの移行 |
| FSx for ONTAP iSCSI パフォーマンスベンチマーク | Early Preview の結果を「GA 時のパフォーマンス保証」として記載 |
| 移行後の ONTAP 機能動作確認 | Early Preview の NDA 対象情報の公開 |
| ツール選択の判断材料としての結果共有 | GA されていない機能を「推奨」として顧客に案内 |
| NetApp との技術的フィードバック共有 | 未公開の Early Preview 手順をブログに掲載（公開可能範囲を事前確認） |

**「So what?」— この検証で何が分かれば、誰が何を判断できるか:**

> この検証の結果をもって、ONTAP NFS データストアを使用中の VMware 顧客が「データディスクを FSx for ONTAP に移行する価値があるか」「MGN/CMC と比較して Shift Toolkit を選ぶ理由があるか」を定量的に判断できる状態を目指す。

### Phase 1: 環境準備

#### AWS 側

| リソース | 構成 | 備考 |
|---------|------|------|
| VPC | 専用 VPC + Private Subnets (2 AZ) | FSx for ONTAP Multi-AZ 用 |
| FSx for ONTAP | Multi-AZ, SSD 1TB, 512 MB/s throughput | iSCSI LUN 対応確認 |
| EC2 (テスト) | Amazon Linux 2023 + Windows Server 2022 | 移行先インスタンス |
| Security Groups | iSCSI (3260), SSH (22), RDP (3389), NFS (2049) | FSx for ONTAP ↔ EC2 通信 |
| VPN/DX | Site-to-Site VPN または Direct Connect | オンプレ ↔ AWS 接続 |
| IAM | FSx for ONTAP 管理ロール + EC2 プロビジョニング権限 | 最小権限原則 |

#### オンプレ側

| リソース | 構成 | 備考 |
|---------|------|------|
| vCenter | 7.0.3 以降 | Shift Toolkit 接続先 |
| ESXi | テスト用ホスト | NFS データストア必須 |
| ONTAP | 9.14.1 以降 (NFS ボリューム) | Shift Toolkit 動作前提 |
| Shift Toolkit | Windows Server 上にインストール | 100GB ディスク最小 |

#### ネットワーク

- オンプレ ↔ AWS 間の HTTPS (443) 通信確認
- DNS 解決の確認
- SnapMirror 用ポート (11104/11105) の開放

### Phase 2: 移行テスト

#### テスト VM 選定

> ⚠️ **テストデータポリシー**: テスト VM には本番データを一切使用しない。OS インストール + テスト用ダミーデータ（dd or fio で生成したランダムデータ）で構成する。これにより、検証エビデンスのスクリーンショット公開時のデータ漏洩リスクを排除する。

| VM | OS | ディスク構成 | 用途 | EC2 ターゲット |
|----|-----|-----------|------|--------------|
| test-linux-01 | RHEL 9.x | OS: 50GB + Data: 100GB | Linux 基本検証 | m5.large (2 vCPU, 8 GiB) |
| test-win-01 | Windows Server 2022 | OS: 80GB + Data: 200GB | Windows 基本検証 | m5.xlarge (4 vCPU, 16 GiB) |
| test-app-01 | Ubuntu 2024 | OS: 50GB + Data: 500GB | 大容量ディスク変換速度検証 | m5.large (2 vCPU, 8 GiB) |

**EC2 インスタンスタイプ選定基準:**

- 移行元 VM の vCPU/RAM に対して同等以上の EC2 インスタンスタイプを選定
- Nitro ベース（m5 以降）を使用（ENA/NVMe ドライバ動作確認のため）
- 検証用のため最小限のサイズ。本番サイジングは AWS Pricing Calculator + ONTAP Storage Efficiency 見積もりで算出

#### 移行手順（予定）

1. SnapMirror でオンプレ ONTAP → FSx for ONTAP へデータディスクをレプリケーション
2. Shift Toolkit で VMDK → 中間フォーマット変換（Early Preview の手順に従う）
3. OS ディスクから AMI 作成（VM Import/Export or CMC 利用）
4. EC2 インスタンス起動 + FSx for ONTAP iSCSI LUN アタッチ
5. ネットワーク設定・アプリケーション動作確認

**注意**: 具体的な手順は Early Preview の機能仕様確認後に更新する。

### Phase 3: 検証項目

#### 3a. 基本検証（移行の正当性確認）

| # | 検証項目 | 判定基準 | ツール |
|---|---------|---------|-------|
| 1 | 移行後 VM 起動確認 | OS 正常ブート、ログインが可能 | EC2 Console, SSH/RDP |
| 2 | データ整合性 | sha256sum 一致（移行前後の全ファイル） | sha256sum, diff |
| 3 | ネットワーク接続 | IP 設定維持、外部通信可能 | ping, curl, ss |
| 4 | アプリケーション動作 | テストアプリが正常応答 | アプリ固有テスト |
| 5 | 移行所要時間 | 変換時間の実測（VMDK サイズ別） | Shift Toolkit ジョブログ |
| 6 | ロールバック | ソース VM がそのまま起動可能 | vCenter |

#### 3b. EC2/Nitro 固有検証（ドライバ・メタデータ・時刻同期）

| # | 検証項目 | 判定基準 | ツール | 備考 |
|---|---------|---------|-------|------|
| 7 | ENA ドライバの動作 | Enhanced Networking 有効、ネットワークスループット正常 | `ethtool -i eth0`, `dmesg | grep ena` | Nitro 系インスタンスでは ENA 必須 |
| 8 | NVMe ドライバの動作 | EBS ボリュームが /dev/nvme* で認識 | `lsblk`, `nvme list` | Nitro 系では NVMe ブロックデバイス |
| 9 | EC2 インスタンスメタデータ | IMDSv2 でメタデータ取得可能 | `curl -H "X-aws-ec2-metadata-token: ..." http://169.254.169.254/` | VMware Tools 削除後の動作確認 |
| 10 | Windows ライセンス状態 | BYOL or License Included の判定、アクティベーション状態 | `slmgr /dli` | BYOL の場合 KMS or MAK 設定要確認 |
| 11 | タイムゾーン/NTP | UTC 設定 + chrony/w32tm 正常同期 | `timedatectl`, `chronyc sources` | VMware Tools 時刻同期からの切り替え |

#### 3c. FSx for ONTAP iSCSI ストレージ検証（構成記録とベンチマーク）

**FSx for ONTAP 検証構成の記録要件（全ベンチマークに対して必須）:**

| パラメータ | 検証構成（予定） | 記録方法 |
|-----------|----------------|---------|
| FSx for ONTAP デプロイメントタイプ | Multi-AZ | FSx for ONTAP Console / CLI |
| SSD ストレージ容量 | 1 TB | FSx for ONTAP Console |
| プロビジョニングスループット | 512 MB/s | FSx for ONTAP Console |
| Flash Cache | 有効 / 無効（両方測定） | FSx for ONTAP Console |
| iSCSI セッション数 | 4 セッション | `iscsiadm -m session` |
| EC2 インスタンスタイプ | m5.xlarge | EC2 Console |
| EC2 ネットワーク帯域 | 最大 10 Gbps | インスタンス仕様 |
| LUN サイズ | 100 GB / 500 GB | ONTAP CLI |

**fio ベンチマークパラメータセット:**

```bash
# テスト 1: 4K Random Read (IOPS 重視)
fio --name=4k-randread \
    --ioengine=libaio --direct=1 \
    --bs=4k --iodepth=64 --numjobs=4 \
    --rw=randread --size=10G \
    --runtime=300 --time_based \
    --ramp_time=30 \
    --group_reporting \
    --output-format=json

# テスト 2: 4K Random Write (IOPS 重視)
fio --name=4k-randwrite \
    --ioengine=libaio --direct=1 \
    --bs=4k --iodepth=64 --numjobs=4 \
    --rw=randwrite --size=10G \
    --runtime=300 --time_based \
    --ramp_time=30 \
    --group_reporting \
    --output-format=json

# テスト 3: 64K Sequential Read (Throughput 重視)
fio --name=64k-seqread \
    --ioengine=libaio --direct=1 \
    --bs=64k --iodepth=32 --numjobs=4 \
    --rw=read --size=10G \
    --runtime=300 --time_based \
    --ramp_time=30 \
    --group_reporting \
    --output-format=json

# テスト 4: 64K Sequential Write (Throughput 重視)
fio --name=64k-seqwrite \
    --ioengine=libaio --direct=1 \
    --bs=64k --iodepth=32 --numjobs=4 \
    --rw=write --size=10G \
    --runtime=300 --time_based \
    --ramp_time=30 \
    --group_reporting \
    --output-format=json
```

**ベンチマーク結果の記録フォーマット（各テストで必須）:**

- IOPS: avg / P50 / P90 / P95 / P99 / Max
- Throughput (MB/s): avg
- Latency (μs): avg / P50 / P90 / P95 / P99 / Max
- benchmark_run_id: `{test_name}_{fsxn_config}_{timestamp}`

> **重要注記（全ベンチマーク結果に付与）:** 本測定結果は特定の検証環境における**サイジングリファレンス**であり、**FSx for ONTAP のサービスリミットを示すものではない**。実環境でのパフォーマンスは、ワークロード特性、ネットワーク構成、FSx for ONTAP の設定により異なる。

| # | 検証項目 | 判定基準 | ツール | 備考 |
|---|---------|---------|-------|------|
| 12 | iSCSI 接続確認 | LUN がマウント可能、R/W 正常 | `iscsiadm`, `lsblk`, `mount` | マルチパス構成含む |
| 13 | マルチパス (MPIO) 構成 | 2パス以上のアクティブパス確認 | `multipath -ll` (Linux) / `mpclaim` (Windows) | FSx for ONTAP Multi-AZ の場合は preferred/non-preferred |
| 14 | FSx for ONTAP iSCSI IOPS (4K Random) | 実測値を記録（ベースライン作成） | `fio --bs=4k --iodepth=64 --rw=randread` | FSx for ONTAP 構成: SSD容量, スループット, Flash Cache 有無を記録 |
| 15 | FSx for ONTAP iSCSI Throughput (64K Seq) | 実測値を記録 | `fio --bs=64k --iodepth=32 --rw=read` | プロビジョニングスループットとの比較 |
| 16 | 共有スループット影響 | NFS/SMB 並行アクセス時の iSCSI 性能変化 | fio + 並行 NFS コピー | **FSx for ONTAP は NFS/SMB/iSCSI でスループットを共有する** — これを実測で確認 |
| 17 | ONTAP Snapshot | スナップショット作成・リストアが正常完了 | ONTAP CLI: `volume snapshot create/restore` | FSx for ONTAP Console からも確認 |
| 18 | ONTAP FlexClone | LUN クローンが高速完了（秒単位） | ONTAP CLI: `volume clone create` | データコピーなしの確認 |
| 19 | Storage Efficiency | Dedup/Compression の有効化と効率レポート | ONTAP CLI: `volume efficiency show` | 移行後データでの実効削減率 |
| 20 | SnapMirror レプリケーション | オンプレ→FSx for ONTAP のレプリケーション正常完了 | ONTAP CLI: `snapmirror show` | 初期転送 + 増分の動作確認 |

#### 3d. コスト検証（FinOps 観点）

| # | 検証項目 | 判定基準 | ツール |
|---|---------|---------|-------|
| 21 | FSx for ONTAP 月額コスト試算 | 検証構成での月額を算出 | AWS Pricing Calculator + 実測使用量 |
| 22 | EBS 同等構成コスト試算 | 同容量・同 IOPS を EBS で実現した場合の月額 | AWS Pricing Calculator |
| 23 | TCO 比較レポート | FSx for ONTAP vs EBS のみ構成の月額差を表形式で提示 | スプレッドシート |
| 24 | Storage Efficiency によるコスト削減効果 | Dedup/Compression 後の実効容量での再計算 | ONTAP CLI + Pricing |

#### 3e. 移行後運用検証（Reliability/Ops 観点）

| # | 検証項目 | 判定基準 | ツール |
|---|---------|---------|-------|
| 25 | CloudWatch 監視 | FSx for ONTAP メトリクス (IOPS, Throughput, Latency) が取得可能 | CloudWatch Console |
| 26 | CloudWatch Alarms | 閾値超過時のアラーム発報確認 | CloudWatch Alarms + SNS |
| 27 | バックアップ (AWS Backup) | FSx for ONTAP ボリュームの AWS Backup 統合確認 | AWS Backup Console |
| 28 | 障害時ロールバック手順 | EC2 障害時に Snapshot からの復旧手順を文書化・実行 | ONTAP Snapshot + EC2 再作成 |
| 29 | DR 構成（SnapMirror Cross-Region） | 別リージョンへの FSx for ONTAP レプリケーション確認 | SnapMirror + FSx for ONTAP (DR リージョン) |

### Phase 4: ドキュメント・記事化

#### 成果物一覧

- 検証レポート（本リポジトリ `docs/ja/` 配下）
- アーキテクチャ図（draw.io/diagrams.net）
- スクリーンショット・エビデンス（`verification/` 配下）
- dev.to ブログシリーズ（下記構成案参照）
- CloudFormation テンプレート（`templates/` 配下）
- 自動化スクリプト（`scripts/` 配下）

---

## 7. ブログシリーズ構成案（dev.to）

### シリーズ名: 「VMware から EC2 + FSx for ONTAP への移行 — Shift Toolkit Early Preview 検証記」

| # | タイトル案 | 内容 | 対象読者 |
|---|-----------|------|---------|
| 1 | VMware 移行の選択肢を整理する — なぜ EC2 + FSx for ONTAP なのか | 背景、ツール比較、FSx for ONTAP の価値 | 全ペルソナ |
| 2 | Shift Toolkit とは何か — FlexClone が変える VM 移行の常識 | ツール概要、FlexClone の仕組み、デモ | NetApp/VMware ユーザー |
| 3 | 検証環境構築 — VPC + FSx for ONTAP + VPN の設計と構築 | AWS 環境準備、CFn テンプレート | AWS ユーザー |
| 4 | 実践: Linux VM の移行 — RHEL 9 を EC2 へ | ステップバイステップ手順、スクリーンショット | 全ペルソナ |
| 5 | 実践: Windows VM の移行 — Windows Server 2022 を EC2 へ | Windows 固有の考慮事項、ネットワーク設定 | VMware/AWS ユーザー |
| 6 | FSx for ONTAP iSCSI パフォーマンス検証 | fio ベンチマーク、EBS 比較 | AWS/NetApp ユーザー |
| 7 | ONTAP 運用モデルの継続性 — Snapshot, Clone, SnapMirror on AWS | 移行後の運用確認 | NetApp ユーザー |
| 8 | まとめとベストプラクティス — コスト最適化と今後の展望 | 総括、推奨構成、注意事項 | 全ペルソナ |

### 検証記事・登壇で使える短めのまとめ

NetApp Shift Toolkit は、VMware ESXi、Hyper-V、OLVM、Red Hat OpenShift Virtualization、Proxmox VE など、複数のハイパーバイザー間での VM 移行とディスク形式変換を支援するツールです。NetApp の公式ドキュメントでは、ONTAP FlexClone を活用して VM ディスク変換を高速化し、移行先 VM の作成・構成も管理する GUI ベースのソリューションとして説明されています。[（出典）](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)

今回検証する Early Preview では、VMware ESXi から AWS EC2 への移行が対象となり、データディスクを Amazon FSx for NetApp ONTAP に配置する点が特徴です。FSx for ONTAP は、AWS 上でフルマネージドの ONTAP ファイルシステムを提供し、NFS、SMB、iSCSI、Snapshot、clone、replication、compression、deduplication などを利用できます。[（出典）](https://aws.amazon.com/documentation-overview/netapp-ontap/)

AWS、NetApp、VMware の観点をつなげると、このプレビューは「VMware から EC2 へ移す」だけでなく、「ONTAP のデータ管理機能を活かしながら、AWS 上で VMware ワークロードの次の配置先を検討する」ための重要な検証テーマだと考えています。

---

## 8. Early Preview 注意事項

> ⚠️ **重要**: 以下の事項を常に念頭に置くこと

1. **Early Preview はプロダクション利用向けではない** — 機能、パフォーマンス、サポート範囲が GA 版とは異なる可能性がある
2. **ドキュメントの制約** — Early Preview 固有の手順は公式ドキュメントに完全には反映されていない可能性がある
3. **機能変更の可能性** — GA に向けてワークフロー、対応 OS、パフォーマンス特性が変更される可能性がある
4. **検証結果の記載方法** — 「Early Preview 検証時点（2026年6月）」と明記し、GA 版では異なる可能性があることを注記する
5. **NDA/利用規約** — Early Preview へのアクセスには NetApp との合意が必要な場合がある。公開可能な情報範囲を確認すること
6. **再現性の保証** — Early Preview バージョン、ONTAP バージョン、環境構成を詳細に記録し、再現条件を明確にする

---

## 9. 参考リンク一覧

### NetApp 公式ドキュメント

- [Shift Toolkit Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)
- [Shift Toolkit Migration Workflow](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-migration.html)
- [Shift Toolkit Supported Versions](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-supported-versions.html)
- [Shift Toolkit Installation Prerequisites](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-install-prereqs.html)
- [Migrate VMs to Amazon EC2 - Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-overview.html)
- [Migrate VMs to Amazon EC2 - Architecture & Requirements](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-arch.html)
- [Migrate VMs to Amazon EC2 - Deploy](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-deploy.html)
- [More Migration Options](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-summary.html)

### NetApp ブログ・コミュニティ

- [Simplify and accelerate VM migration with the NetApp Shift Toolkit](https://www.netapp.com/blog/simplify-vm-migration-shift-toolkit/)
- [Effortless VM Migration: Hypervisor hopping with instant cloning](https://community.netapp.com/t5/Tech-ONTAP-Blogs/Effortless-VM-Migration-Hypervisor-hopping-with-instant-cloning-and-zero-data/ba-p/460596)
- [Migrate VMware to Amazon EC2 & iSCSI-based FSx for ONTAP](https://www.netapp.com/blog/aws-fsxn-blg-migrate-vmware-to-amazon-ec2-iscsi-based-fsx-for-ontap/)
- [Migrate VMware Cloud on AWS to Amazon EC2 instances and FSx for ONTAP](https://community.netapp.com/t5/Tech-ONTAP-Blogs/Migrate-VMware-Cloud-on-AWS-to-Amazon-EC2-instances-and-FSx-for-ONTAP/ba-p/458334)

### AWS 公式ブログ・ドキュメント

- [Seamless migration from any VMware environment to FSx for ONTAP and EC2](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/)
- [Expedite VMware migration to EC2 and FSx for ONTAP using BlueXP migration advisor](https://aws.amazon.com/blogs/storage/expedite-vmware-migration-to-amazon-ec2-and-amazon-fsx-for-netapp-ontap-using-bluexp-workload-factory-for-aws-migration-advisor/) <!-- allow:naming -->
- [Amazon FSx for NetApp ONTAP Documentation](https://aws.amazon.com/documentation-overview/netapp-ontap/)
- [Amazon FSx for ONTAP User Guide](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/how-it-works-fsx-ontap.html)
- [AWS VMware Migration Accelerator](https://aws.amazon.com/vmware/migrationaccelerator/)

### AWS Transform 関連ブログ・ドキュメント（2025-12〜2026-06）

- [Accelerating VMware migration: AWS Transform's new experience](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/) (2025-12) — E2E ウォークスルー: discovery→計画→ネットワーク変換→サーバー移行。前提条件（Organizations / IdC）、ジョブ作成手順、Discovery Collector OVA の解説
- [New Capabilities in AWS Transform for VMware](https://aws.amazon.com/jp/blogs/migration-and-modernization/new-capabilities-in-aws-transform-for-vmware/) (2025-05) — ネットワーク変換（VMware→AWS Security Group）と依存関係ベースのウェーブ計画
- [Accelerating VMware Cloud Migration with AWS Transform and PowerCLI](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-cloud-migration-with-aws-transform-and-powercli/) (2026-01) — PowerCLI ベースの VMware インベントリ収集（RVTools / MPA / ME 形式出力）。aws-samples リポジトリで公開
- [Accelerating VMware migrations with MGN replication agent installation automation](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migrations-with-aws-transform-and-mgn-replication-agent-installation-automation/) (2026-06) — 大規模環境での MGN エージェント自動デプロイ
- [Accelerate VMware migration planning using AWS Transform discovery tool](https://www.repost.aws/articles/ARWBQEyEEgQ-i9bNsSjlLJZQ/) (re:Post, 2025-12) — discovery ツールのデプロイと RVTools 連携
- [Simplify server migration to AWS with AWS Transform for VMware](https://aws.amazon.com/blogs/migration-and-modernization/simplify-server-migration-to-aws-with-aws-transform-for-vmware/) (2025-06) — サーバー移行フローの概要
- [Automate large scale network migration using AWS Transform Network Migration APIs](https://aws.amazon.com/blogs/migration-and-modernization/automate-large-scale-network-migration-using-aws-transform-network-migration-apis/) (2025-12) — NW 変換 API による大規模ネットワーク移行自動化
- [Guidance for Automated Setup of AWS Transform for VMware](https://aws.amazon.com/solutions/guidance/automated-setup-of-aws-transform-for-vmware/) (AWS Solutions) — テスト環境を自動構築するガイダンス
- [How AWS Is Using Agentic AI To Reinvent Infrastructure Modernization](https://aws.amazon.com/blogs/migration-and-modernization/how-aws-is-using-agentic-ai-to-reinvent-infrastructure-modernization/) (2026-06) — エージェント型 AI ベースのモダナイゼーション概説
- [AWS Transform VMware — Migrate servers (UserGuide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-migrate-servers.html) — ウェーブ設定、レプリケーション、テスト、カットオーバーの公式手順

> **注意**: FSx for ONTAP をストレージ宛先にする検証ブログは 2026-06-18 時点で未公開（発表が 6/16 のため）。本検証が、FSx for ONTAP 宛先を含む実践的な検証記事の一つになりうる。

### NetApp 公式ブログ

- [Migrate VMware to Amazon EC2 & iSCSI-based FSx for ONTAP](https://www.netapp.com/blog/aws-fsxn-blg-migrate-vmware-to-amazon-ec2-iscsi-based-fsx-for-ontap/) (2026-06) — EC2 + FSx for ONTAP iSCSI 構成への移行。AWS Transform の FSx for ONTAP 連携にも言及

### その他

- [VMware on AWS — Modernization with Amazon EVS & FSx for ONTAP](https://www.netapp.com/aws/fsx-ontap/vmware-cloud/)
- [BlueXP Workload Factory](https://www.netapp.com/bluexp/workload-factory/) <!-- allow:naming -->
- [Cirrus Migrate Cloud on AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-stsxln5eru5wo)
- [NetApp Shift Toolkit Simulator](https://netapp.github.io/shift-simulator/)

---

## 付録: FSx for ONTAP 既知の知見（親プロジェクトからの引用）

以下は別プロジェクト (fsxn-lakehouse-integrations) での検証済み知見:

- **FSx for ONTAP S3 Access Point**: Athena/Glue/Bedrock 連携は検証済み
- **FSx for ONTAP iSCSI**: EC2 からのブロックアクセスが可能（本検証のデータディスク配置に直接関連）
- **ONTAP 9.17.1**: S3 AP 機能利用可能（本検証で使用する ONTAP バージョンの参考）

---

*本ドキュメントは調査フェーズの成果物であり、Early Preview の実機検証結果に基づいて継続的に更新される。*
