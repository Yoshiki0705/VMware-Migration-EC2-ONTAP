# AWS Transform の FSx for ONTAP サポート GA 検証レポート

**目的**: AWS Transform（ATX）における Amazon FSx for NetApp ONTAP サポート GA のスコープを一次情報で確定し、検証アカウント（ap-northeast-1）での実機確認結果と未検証範囲を分離して記録する。

**最終更新**: 2026-09-04
**ステータス**: スコープ確定から、初期化・証明書認証・設定保存・レプリケーション実行・テストインスタンス起動・データ整合性確認、そして **Finalize は承認を得て実行**（12.10）。撤去まで完了（13 章）

---

## 1. 結論

GA したのは **「AWS Transform for migrations（MGN）のターゲットストレージ種別として FSx for ONTAP を選択できる」機能**である。VMware の**データストア**として FSx for ONTAP を提示する機能ではない。この 2 つは別の経路であり、混同すると設計判断を誤る。

| 問い | 回答 | 区分 |
|---|---|---|
| ATX/MGN でサーバー移行のターゲットに FSx for ONTAP を選べるか | 選べる。レプリケーションテンプレートに `FSX_ONTAP` を設定し、読み戻しで永続化を確認 | 実測 |
| VMware モダナイズ経路で FSx for ONTAP が**データストア**として提示されるか | されない。データストアとしての利用は Amazon EVS 側の別機能 | 文書 |
| 移行対象はどのディスクか | データボリュームのみ。**ブートボリュームは常に EBS** | 文書 |
| 接続プロトコルは何か | iSCSI。FlexVol 内の LUN として配置され、ゲストでは DM-Multipath 経由（ALUA）で見える | 実測 |
| EC2/EBS をソースにできるか | **できる**。EC2（Amazon Linux 2023）ソースでレプリケーション → テスト起動 → カットオーバーまで実行し、データ整合性が一致 | 実測 |
| ONTAP 9.20.1 が要件か | 公開ドキュメントに最小 ONTAP バージョンの記載なし。**9.18.1P3D1 でレプリケーションからカットオーバーまで成立**（実測） | 実測 |

**GA 日付の表記差**: AWS Transform User Guide の Change log と Document history はいずれも **2026-08-30**、MGN Release notes は **August 2026**。一方 What's New の URL は `/2026/09/` である。本レポートは機能提供開始日を 2026-08-30、告知を 2026-09 として扱う。

---

## 2. エビデンス区分の定義

本レポートの全記述に以下のタグを付与する。姉妹リポジトリ [FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) の evidence tier との対応も併記する。

| タグ | 意味 | Playbook の tier |
|---|---|---|
| **[実測]** | 本検証環境で実際に実行して確認。実行日・リージョン・アカウント種別を併記 | `verified` |
| **[文書]** | AWS 公式ドキュメントの記載。出典 URL を併記。**実機で確認したことは意味しない** | `documented` |
| **[未確認]** | 実行しておらず、公開情報でも裏取りできていない。調査日と調査範囲を併記 | tier ではなく本文記載 |

「公開ドキュメントに記載が見つからない」ことは製品の挙動についての主張ではなく、ドキュメントの状態についての事実である。そのため [未確認] には**いつ・どこを探したか**を必ず添える。

---

## 3. GA のスコープ確定

### 3.1 GA した機能の範囲 [文書]

What's New の記述は "general availability of Amazon FSx for NetApp ONTAP support **as a storage target for block storage workloads** using AWS Transform for migrations"（出典: [What's New 2026-09](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)）。

Change log では EBS と並ぶ "generally available block storage target" と表現されている（出典: [ATX Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html)）。

つまり GA の対象は、compute / network と同一の移行ウェーブ内でブロックストレージを FSx for ONTAP へ直接レプリケートする経路である。中間ストレージや別ツールを挟まない点が従来との差分。

### 3.2 データストア経路との区別 [文書]

「FSx for ONTAP を VMware のデータストアにする」機能は **Amazon EVS** 側に存在し、ATX の GA とは無関係である。

| 経路 | サービス | FSx for ONTAP の役割 | 到達形態 | 状態 |
|---|---|---|---|---|
| リホスト（EC2 化） | AWS Transform for migrations（MGN） | データボリュームのターゲットストレージ | ゲスト OS から iSCSI | **GA**（2026-08-30） |
| VMware 継続利用 | Amazon EVS | 外部データストア（NFS v3 / v4.1 / NVMe / iSCSI VMFS） | ESXi がマウント | Public Preview |

EVS 側で検証済みとされる機能は [EVS ユーザーガイド](https://docs.aws.amazon.com/evs/latest/userguide/fsx-ontap.html) に一覧がある。GA 告知は 2026-09-04 時点で見つからず、確認できた最新の What's New（[2025-06](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-elastic-vmware-service-fsx-netapp-ontap/)）は public preview と記載している。**EVS 側の状態は [未確認]** として扱う。

### 3.3 リージョン提供状況

- ATX ワークスペース作成可能リージョンに Asia Pacific (Tokyo) が含まれる [文書]（[Supported Regions](https://docs.aws.amazon.com/transform/latest/userguide/regions.html)）
- MGN は ap-northeast-1 対応 [文書]（[What Is AWS Transform MGN?](https://docs.aws.amazon.com/mgn/latest/ug/what-is-mgn.html)）
- FSx for ONTAP ターゲットは「MGN と FSx for ONTAP の両方が利用可能な全リージョン」。**Local Zones は対象外** [文書]
- ap-northeast-1 で両サービスが利用可能であることを Regional availability API で確認 [実測 / 2026-09-04]

---

## 4. API レベルでの実機確認

コンソールのスクリーンショットは取得していない（理由は 5.2）。代わりに、より再現性の高い API モデルレベルの確認結果を示す。

### 4.1 MGN API モデルの確認 [実測 / 2026-09-04]

botocore 同梱の MGN サービスモデル（apiVersion `2020-02-26`）を検査した結果、FSx for ONTAP 対応が API 契約に存在することを確認した。

```
StorageType (enum)                = ['EBS', 'FSX_ONTAP']
StorageConfiguration.storageType  -> StorageType
StorageConfiguration.fsxOntapConfiguration -> FsxOntapConfiguration
FsxOntapConfiguration (required)  = storageVirtualMachineId, credentialsSecretArn
```

再現手順:

```bash
python3 -c "
import botocore, os, glob, gzip, json
base = os.path.dirname(botocore.__file__)
path = glob.glob(os.path.join(base, 'data', 'mgn', '*', 'service-2.json*'))[0]
with gzip.open(path, 'rt') as f:
    model = json.load(f)
print(model['shapes']['StorageType']['enum'])
print(model['shapes']['FsxOntapConfiguration'])
"
```

### 4.2 機能が露出する操作 [実測 / 2026-09-04]

`StorageConfiguration` を入出力に持つ操作は以下 5 つ。レプリケーションテンプレート（全体既定）とサーバー個別のレプリケーション設定の両方で指定できることを意味する。

| 操作 | 入出力 |
|---|---|
| `CreateReplicationConfigurationTemplate` | 入力・出力 |
| `UpdateReplicationConfigurationTemplate` | 入力・出力 |
| `DescribeReplicationConfigurationTemplates` | 出力 |
| `UpdateReplicationConfiguration` | 入力・出力 |
| `GetReplicationConfiguration` | 出力 |

### 4.3 併せて追加された内部要素 [実測 / 2026-09-04]

FSx for ONTAP 対応に伴い、レプリケーションのライフサイクルにも要素が追加されている。障害切り分け時の手がかりになる。

| 種別 | 値 | 示唆 |
|---|---|---|
| 初期化ステップ | `SETUP_FSX_PROXY` | ATX が FSx へ到達するための経路を自動構成する段階が存在する |
| エラー | `FAILED_TO_SETUP_FSX_PROXY` | 上記段階の失敗。ネットワーク・権限を疑う |
| エラー | `FAILED_TO_CREATE_FSX_SNAPSHOT` | ONTAP 側スナップショット作成の失敗 |
| ステージングディスク種別 | `FSX_ONTAP` | ディスク単位でステージング先を指定する枠組みがある |
| ヘルスチェック種別 | `EC2`, `FSx` | FSx を対象とした死活確認が追加されている |

公式ブログは、この経路が PrivateLink 接続を自動確立すると記述している [文書]（[AWS Storage Blog](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)）。上記 `SETUP_FSX_PROXY` はこれに対応すると考えられるが、対応関係そのものは [未確認]。

### 4.4 テンプレートでの選択可否と入力検証の非対称性 [実測 / 2026-09-04]

API モデルの存在確認に加えて、実際にレプリケーションテンプレートへ `FSX_ONTAP` を設定できることを確認した。`initialize-service` が失敗している状態（5.4）でも、テンプレートの作成と更新は成功する。

確認した挙動:

| # | 操作 | 結果 |
|---|---|---|
| 1 | `create-replication-configuration-template` に `storageType=EBS` | 成功。テンプレート生成 |
| 2 | `update-replication-configuration-template` に `storageType=FSX_ONTAP` + 実在する SVM ID + **実在しないシークレット ARN** | **成功**。エラーにならない |
| 3 | 上記を `describe-replication-configuration-templates` で読み戻し | `FSX_ONTAP` と `fsxOntapConfiguration` が**永続化されている**ことを確認（レスポンスのエコーではない） |
| 4 | `storageVirtualMachineId` に存在しない SVM ID | **失敗**。`ResourceNotFoundException`（`resourceType: Storage Virtual Machine`） |

**入力検証は非対称である。** SVM ID は設定時に実在確認されるが、`credentialsSecretArn` は設定時に検証されない。存在しないシークレット ARN を指定してもテンプレートは正常に受理され、永続化される。

運用上の含意は、**シークレット ARN の誤りが設定時点では表面化しない**こと。誤りはレプリケーション開始時まで持ち越され、そこで `FAILED_TO_SETUP_FSX_PROXY`（4.3）として現れると考えられる。この対応関係自体は [未確認] だが、「設定 API が成功したこと」を FSx for ONTAP 連携の成立根拠として扱ってはならない。

確認後、テンプレートは削除した。共用アカウントに誤ったシークレット ARN を持つテンプレートを残すと、後続の利用者が既定値として引き継ぐため。

### 4.5 コンソール UI での確認結果 [実測 / 2026-09-04]

> **訂正**: 本節の初版で「Secret ARN のドロップダウンはタグ付きシークレットのみを候補にする」と記録したが誤りだった。実際は**リージョン内の全シークレット（23 件）を絞り込みなしで列挙する**。タグ付きが 1 件しか無い状態で一覧が空に見えたのは、ドロップダウンの読み込み前に観測したためで、絞り込みの結果ではない。空の描画から規則を推定した誤りである。

コンソールでの操作手順と画面は [MGN コンソール手順書](./atx-fsxn-console-procedure.md) に分離した。ここでは API との差として意味を持つ点のみ記録する。

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | ターゲットストレージの選択 UI | `Storage configuration` に `EBS` と `Amazon FSx for NetApp ONTAP` の 2 タイルが存在 |
| 2 | ブートディスクの扱いの明示 | FSx for ONTAP 選択時に「Data disks will be migrated to FSx for ONTAP. Boot disk is always migrated to EBS as required by Amazon EC2.」を表示。EBS 側のラベルも「EBS volume type (for boot disk)」に変化 |
| 3 | SVM の列挙 | リージョン内の 2 ファイルシステムを横断して 9 SVM を列挙。AD 参加の有無で絞り込まれない |
| 4 | Secret ARN の候補 | **絞り込みなし**。リージョン内の全 23 件を列挙し、タグの無いシークレットも並ぶ |
| 5 | 必須項目の検証 | 未入力保存で 3 項目を拒否（SVM ID / Secret ARN / **追加のセキュリティグループ**） |

**入力検証の強さがコンソールと API で異なる。** 4.4 の通り API は存在しないシークレット ARN を受理するが、コンソールは 3 項目すべてを必須として拒否する。さらに「追加のセキュリティグループ」の必須化は MGN ユーザーガイドの手順記述からは読み取れず、コンソールで初めて判明する制約である。

IaC / CLI で設定する場合、**シークレット ARN の実在と内容は自前で検証する必要がある**。設定 API の成功は連携成立の根拠にならない。コンソールも、必須項目の入力有無は検証するが**シークレットのタグと中身は検証しない**（4.5 の訂正）。

### 4.6 設定の保存と証明書認証 [実測 / 2026-09-04]

必須 3 項目を満たしてテンプレートを保存し、API 読み戻しで永続化を確認した。操作手順は [MGN コンソール手順書](./atx-fsxn-console-procedure.md)。

| 項目 | 結果 |
|---|---|
| `storageType` | `FSX_ONTAP` |
| `storageVirtualMachineId` | 検証用に新規作成した SVM に解決 |
| `credentialsSecretArn` | 作成したシークレットに解決 |
| 証明書認証（証明書あり） | HTTP 200。クラスタ情報を取得 |
| 証明書認証（証明書なし・否定対照） | HTTP 401 |
| ONTAP バージョン | NetApp Release 9.18.1P3D1 |

**ONTAP バージョンは AWS API では取得できない**（7.2）。上記は ONTAP REST API を SSM ポートフォワード経由で叩いて取得した値である。9.18.1P3D1 で設定と証明書認証は成立した。ただしレプリケーション実行時に別のバージョン要件が現れるかは未検証。

証明書は**管理 vserver（クラスタスコープ）**に導入した。作成した SVM には独自の管理 LIF があるため SVM スコープで足りる可能性はあるが未検証（U14）。

なお FSx はクラスタスコープの client-ca 証明書を 2 件あらかじめ導入している（`FSxCAforONTAP-1in<region>`、`AmazonFSxRootCA1for<region>`）。自分で導入した証明書はこれらと併存する。

拒否された時点でテンプレートは書き換わっておらず（`storageConfiguration` は `null` のまま）、検証失敗は書き込みを伴わないことも確認した。その後キャンセルし、既定は `EBS` のまま残している。

---

## 5. 検証環境の現状と実機検証のブロッカー

### 5.1 検証環境の状態 [実測 / 2026-09-04, ap-northeast-1]

| 対象 | 状態 |
|---|---|
| MGN | 未初期化。IAM ロール未作成のため `initialize-service` は失敗する（5.4） |
| FSx for ONTAP ファイルシステム | 2 台、いずれも `AVAILABLE`。別々の VPC に所在 |
| ファイルシステム構成 | ともに `SINGLE_AZ_1` / 1024 GiB / 128 MBps |
| SVM | 9 台、いずれも `CREATED`。うち 3 台は AD 参加済み |
| ONTAP 管理エンドポイントへの到達 | VPC 内の SSM 管理下 Linux ホストから到達可（HTTP 401 = TLS 成立・認証要求） |

**アカウントの性質についての訂正**: 当初このアカウントを「個人検証アカウント」として記述したが、実際には**複数の検証ワークストリームが同居する共用アカウント**である。EC2 が 14 台、候補ファイルシステム上に 6 SVM / 25 ボリュームが存在し、FPolicy・SnapMirror・S3 アクセスポイント・監査ログ・分析系など別目的の検証が並行している。この事実は実機検証の設計に影響する（5.3）。

なお既存ファイルシステムはいずれも Single-AZ であり、Multi-AZ 固有の要件（後述 9.2 のエンドポイント IP レンジ制約）は現時点では適用されない。

### 5.2 スクリーンショットの取得と置換

依頼にはスクリーンショット付きの記録が含まれていたが、本セッションでは取得していない。理由は 2 点。

当初は認証済みブラウザセッションを持たず、かつ MGN 未初期化のため UI 自体が存在せず取得できなかった。その後ブラウザ経由で認証しコンソール初期化に成功したため、**画面キャプチャは取得済み**である。

| 保管先 | 内容 | git |
|---|---|---|
| `verification/screenshots/raw/` | 生画像 | `.gitignore` で除外 |
| `verification/screenshots/masked/` | アカウント ID・IAM ユーザー名・リソース ID・組織内名称を置換済み（11 枚） | コミット対象 |

置換の検証は OCR で行い、**生画像で読めていた文字列が置換後に読めないこと**を対で確認した（9 枚中 8 枚で対照が成立。残る 1 枚はダークテーマで OCR が本文を読めず対照が成立しないため、DOM 上に文字列が存在しない状態で撮影した保証に依拠する）。手順と画面は [MGN コンソール手順書](./atx-fsxn-console-procedure.md) にまとめた。

コンソール画面を記録する場合の到達パスは以下。**MGN の初期化が前提**となる。

```
MGN コンソール → Settings → Replication template → Edit
  → Target storage type で "AWS FSx for ONTAP" を選択
  → Storage Virtual Machine (SVM) ID を選択
  → FSx Storage Secret ARN を入力
```

出典: [FSx for ONTAP configuration — Step 5](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html)

### 5.3 実機検証に必要な作業と承認が必要な理由

エンドツーエンド検証には以下が必要で、うち複数がアカウントに永続的な変更を加える。実行前に個別の承認を求める。

| # | 作業 | 影響 |
|---|---|---|
| 1 | MGN の初期化 | AWS マネージド IAM ロールを作成。アカウント単位の状態変更 |
| 2 | セキュリティグループ 2 つの作成（相互参照） | 新規リソース |
| 3 | クライアント証明書の生成と ONTAP へのインストール、`security login` 作成 | ONTAP 側の構成変更 |
| 4 | Secrets Manager シークレット作成 | 新規リソース。証明書と秘密鍵を保管 |
| 5 | レプリケーションテンプレートの更新 | アカウント既定値の変更 |
| 6 | ソースサーバーへのエージェント導入とレプリケーション | ソースサーバーが別途必要。転送量とステージング費用が発生 |
| 7 | テスト起動 → カットオーバー → **Finalize** | **Finalize は不可逆**（後述 9.1） |

このうち 1 が現時点で失敗しており（5.4）、6 以降には未着手である。また 3 と 6 以降には共用環境固有の制約がある。

**証明書インストール（3）の到達性**: VPC 内の SSM 管理下 Linux ホストから ONTAP 管理エンドポイントへは到達できるが、そのインスタンスプロファイルに `secretsmanager:GetSecretValue` が付与されておらず、fsxadmin 認証情報を取得できない。認証情報を SSM のコマンドパラメータ経由で渡すとコマンド履歴に平文で残るため、共用アカウントでは採らない。IAM の追加付与か、別の認証経路の合意が必要である。

なお fsxadmin シークレットの説明には、2 つのファイルシステムのシークレットが同一ユーザー名を共有しており、誤ったファイルシステムに対して試行すると実アカウントで認証失敗が発生する旨の注意書きがある（過去に認証停止と再設定が 1 回発生している）。総当たり的な試行は行わない。

**レプリケーション（6 以降）の影響範囲**: 移行実行には自動バックアップと ARP の無効化が必要で（8.3）、いずれも**ファイルシステム単位の設定**である。候補ファイルシステムには他ワークストリームの 25 ボリュームが同居しているため、無効化はそれらのデータ保護にも及ぶ。加えて容量指針は「移行データ量の 3 倍、SSD 使用率 80% 以下」であり、1024 GiB のファイルシステムに約 1,166 GiB がシンプロビジョニングで確保済みの現状では、実使用量の確認が前提になる。

### 5.4 initialize-service に必要な前提条件 [実測 / 2026-09-04、訂正 2026-09-08]

> **訂正**: 当初この節は「CLI の初期化が再現性をもって失敗する不具合」として記録していた。**不具合ではなく、こちらの手順の誤りである。** API 経路は 8 件の IAM ロールを**利用者が先に作る**手順になっており、[Initializing AWS Transform MGN with the API](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html) の手順 1 がそれである。`initialize-service` が行うのはサービスリンクロールの作成・インスタンスプロファイルの作成・**既存**ロールの紐付けであり、ロール自体は作らない。以下は当初の観測をそのまま残し、末尾で訂正の根拠を示す。

MGN の初期化は再現性を持って失敗する。

```
$ aws mgn initialize-service --region ap-northeast-1
ValidationException: Failed to create SLR or instance profiles
Additional error details:
  reason: OTHER
```

失敗時に残る状態:

| リソース | 結果 |
|---|---|
| サービスリンクロール `AWSServiceRoleForApplicationMigrationService` | **作成される** |
| インスタンスプロファイル 4 件（ReplicationServer / ConversionServer / LaunchInstanceWithDrs / LaunchInstanceWithSsm） | **作成されるが、ロールが 1 つも紐づかない空の状態** |
| 対応する IAM ロール 4 件 | **作成されない** |

空のインスタンスプロファイルを削除して再実行しても、同じ状態が再生成される。したがって空のプロファイルは原因ではなく症状であり、**ロール作成の段階が失敗している**。

切り分けとして除外できた要因:

| 要因 | 確認結果 |
|---|---|
| 呼び出し元の権限不足 | `AdministratorAccess` を保持 |
| SCP による拒否 | 当該アカウントは Organizations の管理アカウントであり、SCP は管理アカウントに適用されない |
| IAM クォータ超過 | ロール 452 / 1000、インスタンスプロファイル 40 / 1000 |
| 既存リソースとの名前衝突 | 同名のロールは存在しない |
| CloudTrail 上の IAM エラー | ~~当該時刻の IAM イベントはいずれのリージョンにも現れない~~ → **この確認が誤り。** us-east-1 に記録されている（下記の訂正を参照）。当時の照会は時刻範囲を取り違えていた可能性が高い。CloudTrail の出力はローカル時刻で表示される一方、`--start-time` / `--end-time` は UTC で解釈される |

エージェント型レプリケーションはこれらのインスタンスプロファイルとロールを必要とするため、**この失敗が解消しない限り E2E 検証には進めない**。テンプレート設定（4.4）は初期化を必要としないため実測できた。

**コンソール経路では成功する** [実測 / 2026-09-04]。`設定 → レプリケーションテンプレート` を開くとセットアップ画面へリダイレクトされ、`サービスをセットアップ` の実行で初期化が完了した。CLI と同一の認証情報・同一リージョンでの結果である。

初期化後に作成されたロールは 9 件で、CLI 経路では 1 件も作られなかったものが揃っている。うち 2 件は FSx for ONTAP 対応で追加された専用ロールである。

| ロール | 管理ポリシー | 示唆 |
|---|---|---|
| `AWSApplicationMigrationFsxProxyRole` | `AWSApplicationMigrationFSxProxyPolicy` | FSx への到達経路 |
| `AWSApplicationMigrationFsxProxyLinkRole` | `AWSApplicationMigrationFSxProxyVPCPolicy` | VPC 側の接続。名称と権限から 4.3 の `SETUP_FSX_PROXY` および公式ブログ記載の PrivateLink 自動確立に対応すると考えられる |

この 2 ロールの存在は、FSx for ONTAP 対応が初期化時点でロール構成に反映されることを示す。初期化を FSx for ONTAP 対応前に済ませた環境では、テンプレート画面の `サービスのアクセス許可を再初期化` が必要になる理由がこれで説明できる。

#### 訂正の根拠 [実測 / 2026-09-08]

CloudTrail（us-east-1、IAM はグローバルサービスのためここに記録される）で失敗時の呼び出し列を確認した。

| 経路 | `CreateRole` の呼び出し回数 | 観測された列 |
|---|---|---|
| CLI（2026-09-03 20:31 UTC、失敗） | **0 回** | `CreateServiceLinkedRole` → `CreateInstanceProfile` × 4 → `AddRoleToInstanceProfile` × 4 が全て `NoSuchEntityException`（`The role with name AWSApplicationMigration...Role cannot be found.`） |
| コンソール（2026-09-04 06:13 UTC、成功） | **8 回** | ロールを作成したうえでプロファイルへ紐付け |

`initialize-service` はロールを作ろうとしていない。存在しないロールをプロファイルへ紐付けようとして失敗している。これは [API での初期化手順](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html) の記述と一致する。

> Once the policies are attached to the roles, run the `aws mgn initialize-service` command. This will automatically create the service-linked role, create instance profiles, and add Roles to Instance Profiles.

**正しい手順**（API / IaC 経路）:

1. 8 件のロールを `CreateRole` で作成し、指定の管理ポリシーをアタッチする（同ページの表）。FSx for ONTAP をターゲットにする場合、`AWSApplicationMigrationFsxProxyRole` と `AWSApplicationMigrationFsxProxyLinkRole` もこの 8 件に含まれる
2. `aws mgn initialize-service`
3. `aws mgn create-replication-configuration-template` と `aws mgn create-launch-configuration-template`

**再検証**: ロールが揃った状態で `aws mgn initialize-service --region ap-northeast-1` は成功する（exit 0、2026-09-08 実測）。ただし**この再実行にはコントロールが無い**。失敗条件を再現するにはロールを削除する必要があり、稼働中の検証環境を壊すため実施していない。根拠は上記の CloudTrail の記録であって、再実行の成功ではない。

**含意**: この失敗を「CLI の不具合」や「アカウント側の問題」と解釈すると誤る。**API 経路の前提条件が公開ドキュメントに記載されており、それを踏んでいなかった。** コンソール経路が成功したのは、コンソールがロール作成まで代行するためである。

> **ドキュメントに残る不整合**: 同ページ冒頭は初期化の説明として "The required IAM roles and policies will be created." と書いており、手順 1 で利用者にロール作成を求める記述と読み合わせると、API 経路では誤読を招く。ここは F4 として残す。

---

### 5.5 影響範囲のスコープ整理 [文書 + 実測 / 2026-09-04]

「共用ファイルシステムのどこまでが隔離できるか」は項目ごとに違う。専用 SVM を作る方針は 4 項目のうち 3 項目に有効である。

| 対象 | スコープ | 専用 SVM で隔離できるか | 根拠 |
|---|---|---|---|
| MGN が作るボリューム / LUN / igroup | SVM | できる | 8.1 |
| ARP | ボリューム単位、または SVM 既定 | できる | `security anti-ransomware volume enable -volume X -vserver Y` / `vserver modify -anti-ransomware-default-volume-state`（[文書](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/enable-ARP.html)） |
| 自動バックアップ | **ファイルシステム単位・全ボリューム対象** | できない | 「Automatic daily backups... are file system settings, and apply to all volumes on your file system」。**retention を 0 にすると既存の自動バックアップも削除される**（[文書](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-backups.html)） |
| client-ca 証明書 + `security login` | 管理 vserver（クラスタ） | できない | 公式手順の `vserver_name` はファイルシステム ID 形式。追加のみで可逆 |

**本検証環境では自動バックアップが既に無効**であることを確認した（バックアップ 0 件、FSx を対象とする AWS Backup プランも 0 件）。したがってバックアップに関する制約は本環境では該当しない。他環境へ持ち込む際は再確認が必要である。

### 5.6 SVM 数の上限とスループット容量の連動 [実測 + 文書 / 2026-09-04]

専用 SVM を当初 6 SVM のファイルシステムに作ろうとして `ServiceLimitExceeded`（`STORAGE_VIRTUAL_MACHINES_PER_FILE_SYSTEM`）で失敗した。**SVM 数の上限はスループット容量に連動する**。

| スループット（1 HA ペア） | 最大 SVM 数（IPv4） |
|---|---|
| 128 / 256 / 384 | 6 |
| **512** | **14** |
| **768** | **6** |
| 1,024 | 14 |
| 2,048 | 24 |

出典: [Managing FSx for ONTAP storage virtual machines](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-svms.html)

768 MBps の上限が 512 MBps より少なく、**単調増加ではない**。128 MBps で上限に達している環境で SVM を増やすには 512 MBps への増設が必要になり、スループットは課金対象であるため共用ファイルシステムでは費用判断を伴う。

そのため本検証では、SVM 枠に余裕があり同居ワークストリームの少ない別のファイルシステムを選んだ。当該ファイルシステムの空き容量はアグリゲート 861.8 GiB に対し使用 50.0 GiB（利用率 5.8%）で、推奨上限 80% に対して余裕がある。

E2E 検証を他環境で行う場合は、**専用ファイルシステム**を用意する方が影響範囲を限定できる。

## 6. EC2/EBS ソースからの移行可否

### 6.1 ドキュメント上の可否 [文書]

MGN のソースとして Amazon EC2 は対象に含まれる。AWS Architecture Blog は、物理基盤・VMware vSphere・Microsoft Hyper-V・**Amazon EC2**・Amazon VPC からの移行に対応すると記述している（出典: [Multi-Region Migration using AWS Application Migration Service](https://aws.amazon.com/blogs/architecture/multi-region-migration-using-aws-application-migration-service/)）。

FSx for ONTAP ターゲットの制約は「**エージェント型レプリケーションのみ**」である [文書]。EC2 ソースはエージェント型で扱うため、ドキュメント上は「EC2/EBS をソースに EC2 + FSx for ONTAP へ移行」は成立する。

### 6.2 実機での成否 [実測]

**成立した。** Amazon Linux 2023 の EC2 インスタンス（ブート 8 GiB + データ 4 GiB × 2）をソースとして、レプリケーション → テスト起動 → カットオーバーまで実行し、データ整合性が一致した（12 章）。

| 6.2 で未確認としていた項目 | 現在の状態 |
|---|---|
| 所要時間（初期同期・カットオーバー） | **実測済み**（12.1、12.9） |
| LUN / ボリューム変換の実挙動 | **実測済み**（12.3、12.9） |
| FlexClone 作成の所要時間 | **実測済み**。LAUNCH フェーズ 337 秒に含まれる（12.9） |
| Finalize 時の split の所要時間 | **実測済み**。約 3 分後に開始し 60 秒未満で完了（7.93 GiB、12.10） |
| EC2 ソース特有の落とし穴 | **2 件発見**。`/tmp` の tmpfs 枯渇（12.5）と NVMe デバイス名の再列挙による割り当て反転（12.8） |

### 6.3 ブロッカーの不在

「EC2/EBS ソースが不可なら、どの機能待ちか」という問いに対する回答は、**機能待ちではない**。ドキュメント上の機能ゲートは見つからず、実機でも ONTAP 9.18.1P3D1 でカットオーバーまで成立した。当初のブロッカーは MGN の CLI 初期化失敗（5.4）だけであり、コンソール経路で解消した。

---

## 7. ONTAP バージョン要件の扱い

### 7.1 公開ドキュメントでの確認結果 [未確認]

2026-09-04 時点で、以下を対象に最小 ONTAP バージョンの記載を探したが**見つからなかった**。

- [FSx for ONTAP configuration（MGN ユーザーガイド）](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html) の Prerequisites および Known limitations
- [MGN Release notes](https://docs.aws.amazon.com/mgn/latest/ug/mgn-release-notes.html)
- [ATX Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html)
- [AWS Storage Blog の解説記事](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)

Prerequisites に挙げられているのは MGN の初期化状態、VPC 構成と IPv4 到達性、OS パッケージリポジトリへの外向き到達性のみで、ONTAP バージョンへの言及はない。

したがって社内で言及されている「9.20.1 ターゲット」は、**公開情報では裏取りできない**。本レポートの結論には含めない。

実機では **ONTAP 9.18.1P3D1 でレプリケーションからカットオーバーまで成立した**（12 章）。バージョン起因の失敗は観測していない。ただしこれは 1 バージョンでの 1 回の実測であり、下限を特定したわけではない。

### 7.2 稼働中バージョンの確認手段 [実測 / 2026-09-04]

付随して判明した点として、**FSx の AWS API は ONTAP のソフトウェアバージョンを返さない**。`describe-file-systems` のレスポンスにバージョンを示すフィールドは存在しない（`FileSystemTypeVersion` は ONTAP では `None`、`OntapConfiguration` 配下にも該当フィールドなし）。これは仕様として文書化されている: [`FileSystem`](https://docs.aws.amazon.com/fsx/latest/APIReference/API_FileSystem.html) の `FileSystemTypeVersion` は "The **Lustre version** of the Amazon FSx for Lustre file system, which can be `2.10`, `2.12`, or `2.15`" と定義されており、ONTAP のバージョンを運ぶ項目ではない。

```
top-level keys      : AdministrativeActions, CreationTime, FileSystemId, FileSystemType,
                      KmsKeyId, Lifecycle, NetworkInterfaceIds, NetworkType,
                      OntapConfiguration, OwnerId, ResourceARN, StorageCapacity,
                      StorageType, SubnetIds, Tags, VpcId
OntapConfiguration  : DeploymentType, DiskIopsConfiguration, Endpoints, HAPairs,
                      PreferredSubnetId, ThroughputCapacity,
                      ThroughputCapacityPerHAPair, WeeklyMaintenanceStartTime
```

バージョンを確認するには ONTAP CLI（`cluster image show`）または ONTAP REST API（`/api/cluster?fields=version`）を用いる。管理エンドポイントは VPC 内部からのみ到達可能なため、VPC 内の踏み台または EC2 が必要である。本セッションの実行ホストからは到達しないことを確認した。

この点は運用上の含意を持つ。バージョン依存の要件が将来ドキュメント化された場合、**充足しているかどうかを AWS API だけでは判定できない**。

---

## 8. 移行後のストレージ構造と運用上の注意

すべて [文書]。出典は [FSx for ONTAP configuration](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html) および [AWS Storage Blog](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)。

### 8.1 LUN とボリュームの配置

移行時、**1 ソースサーバーにつき 1 ボリューム**が作成され、各ディスクはそのボリューム内の**個別 LUN** として配置される。ディスク 3 本のサーバーは「1 ボリューム + 3 LUN」になる。

ONTAP の推奨構成は 1 ボリューム : 1 LUN であり、この構成ではスナップショットポリシー・階層化ポリシー・ストレージ効率をディスク単位に分けられない。移行後に `lun move start` で個別ボリュームへ移設できる。この操作は無停止で、ホスト側の iSCSI 再設定を必要としない。

### 8.2 引き継がれない設定

ソースが既存の ONTAP である場合、アクセス権限・quota・スナップショットポリシー・スケジュールは**自動移行されない**。移行後にターゲット側で再設定する。

### 8.3 Finalize 前に対処すべき項目

| 項目 | 内容 |
|---|---|
| 自動バックアップ | FSx for ONTAP の自動バックアップは既定で有効。バックアップが作成したロック済みスナップショットが FlexClone の split を阻害しうる。Finalize 前に無効化し、クリーンアップ完了（最大 24 時間）を待ってから再有効化する |
| ARP | ONTAP の Autonomous Ransomware Protection が有効な場合、移行前に無効化する。レプリケーションボリュームの削除を阻害しうる。カットオーバー後に再有効化する |

### 8.4 MGN 管理リソースへの介入禁止

MGN が管理する FSx for ONTAP リソース（LUN、igroup、スナップショット）の名称変更・変更を行ってはならない。移行が破綻し、**最初からやり直しになる**。

---

## 9. 制約・リスク・前提

### 9.1 不可逆操作

**Finalize は不可逆**である。この段階で ATX は FlexClone を親のレプリケーションボリュームから分離（split）し、レプリケーションを停止、ステージングリソースを破棄する。実行前に、カットオーバーインスタンスでの疎通確認・受け入れテストを完了させる。

**この記述は実測で確認した**（12.10）。Finalize 後に `change-server-life-cycle-state` を呼ぶと拒否され、エラーメッセージは「移行をやり直すにはレプリケーションエージェントを再導入せよ」と示す。つまり戻す手段はレプリケーションのやり直しだけである。

不可逆になる機構と、それ以前にどこまで戻れるかは 9.7 に整理した。

Finalize 前であればロールバック可能で、カットオーバーインスタンスに問題があれば "Ready for cutover" 状態へ戻せる。レプリケーションは停止しておらず、再ベースラインは不要。

もう 1 点、レプリケーション中のサーバーに対してストレージ種別を変更すると、**現在のレプリケーションが終了し最初からやり直しになる**。ストレージ種別は開始前に決める。

### 9.2 構成上の制約

| 制約 | 内容 |
|---|---|
| ブートボリューム | 常に EBS。FSx for ONTAP から直接ブートはできない |
| レプリケーション方式 | エージェント型のみ |
| サーバー内混在 | 1 ソースサーバーのデータボリュームは全て同一ストレージ種別。EBS と FSx for ONTAP の混在は不可 |
| ファイルシステム数 | 1 アカウントで同時に最大 5 台。超える場合はフェーズ分割 |
| igroup 上限 | Single-AZ で 256、Multi-AZ で 512。MGN はレプリケーション時にソースサーバーごと、起動時にターゲットインスタンスごとに 1 つ作成するため、1 ファイルシステムあたりのサーバー数を設計時に見積もる |
| Local Zones | 対象外 |
| Multi-AZ のエンドポイント | エンドポイント IPv4 レンジを **VPC CIDR の外**に、RFC 1918 空間から明示指定する必要がある（unallocated / floating は不可） |

### 9.3 容量とスループットの前提

| 項目 | 指針 |
|---|---|
| ストレージ容量 | 移行データ量の **3 倍**を確保。レプリケート済みデータ、起動用の変換済みボリューム、削除待ちの元ボリュームが同時に存在するため。削除はバックグラウンド処理で、解放は即時ではない |
| SSD 使用率 | 移行期間中 80% 以下に維持 |
| スループット | 全ソースサーバーの平均読み取りと書き込みの合計に 15% のヘッドルームを加え、サポートされる値へ切り上げる。変更には時間がかかるため開始前に決める |
| 縮小 | 第 2 世代（Single-AZ 2 / Multi-AZ 2）では移行後に容量を減らせる。スループットは移行後に下げられる |

### 9.4 権限と認証の前提

| 項目 | 内容 |
|---|---|
| MGN 初期化 | エージェント型レプリケーションで初期化済みであること。**FSx for ONTAP 対応前に初期化した環境では、Settings → Replication template → Reinitialize Service Permissions が必要** |
| 認証方式 | 証明書ベース。ONTAP REST API と iSCSI ターゲットへのアクセスに必須。CHAP は使用しない |
| 秘密鍵形式 | PKCS#8（`-----BEGIN PRIVATE KEY-----`）。PKCS#1 の場合は `openssl pkcs8 -topk8` で変換 |
| シークレット構造 | キー名は厳密に `cert` と `key`。`certificate` / `private_key` は不可。`username` フィールドを含めない |
| シークレットのタグ | `AWSApplicationMigrationServiceManaged` = `True` |
| 証明書の発行元 | テスト用途は自己署名で可。本番は AWS Private CA または社内 CA を推奨 |

### 9.5 ネットワークの前提

| 項目 | 内容 |
|---|---|
| 配置 | FSx for ONTAP と MGN インスタンスは同一アカウント・同一リージョン。VPC は同一でも別でもよいが相互に到達可能であること。IPv4 必須 |
| ポート | iSCSI 3260、ONTAP REST API / 管理 443、ソースからのレプリケーション 1500 |
| SG 構成 | MGN 起動インスタンス用と FSx for ONTAP 用の 2 つを相互参照させる。FSx 側の inbound で MGN 側 SG を source に指定することで、MGN 起動インスタンス以外を既定で遮断できる |
| MGN サービストラフィック | FSx のプリファード / スタンバイ両サブネットの CIDR から 443 を許可する必要がある |
| 外向き到達性 | ステージングサブネットと起動サブネットの両方から OS パッケージリポジトリへ到達できること。MGN が iSCSI initiator と multipath パッケージを自動導入するため |
| AZ 配置 | ターゲット EC2 はファイルシステムのプリファードファイルサーバーと同一 AZ に配置し、レイテンシとクロス AZ 転送費用を抑える |

### 9.6 タグ付けの注意

MAP 2.0 のタグは FSx for ONTAP **ファイルシステム**には付与されるが、**個別のボリュームには付与されない**。ボリューム単位でのコスト配分を前提にしている場合は影響する。

---

### 9.7 移行ライフサイクルと切り戻し可能な範囲 [文書]

出典: [Migrate VMware Storage to Amazon FSx for NetApp ONTAP using AWS Transform（AWS Storage Blog）](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)

公式ブログは移行を 5 段階に分けて説明している。**Finalize がなぜ不可逆なのか、それ以前はなぜ何度でも戻れるのかは、FlexClone の使い方で決まる。**

| 段階 | 内容 | レプリケーションの状態 |
|---|---|---|
| 1. 継続レプリケーション | 初回フルコピー後、変更分のみを継続転送。中断しても途中から再開し、最初からやり直さない | 稼働中。ソースは無停止 |
| 2. 非破壊・反復可能なテスト | レプリケーション済みボリュームの **FlexClone** を作成し、iSCSI でテストインスタンスに接続（マルチパス I/O は自動構成）。ブートは EBS | **継続。FlexClone は独立しているためレプリケーションは中断しない** |
| 3. カットオーバー | 先行するテストインスタンスと依存リソースを削除してから、最新状態でカットオーバーインスタンスを起動 | 継続 |
| 4. ロールバック | カットオーバー後も問題があれば「Ready for cutover」へ戻せる。**再ベースライン不要**で、何度でも繰り返せる | **継続。カットオーバーはレプリケーションを終了させない** |
| 5. Finalize | FlexClone を親ボリュームから分離（split）し、独立ボリュームにする。ステージングリソースを破棄し、ソースを「Cutover complete」にする | **停止。ここで初めて止まる** |

読み取れる要点は 3 つある。

**テストが繰り返せるのは FlexClone が独立しているため。** FlexClone は元ボリュームとブロックを共有する即時の書き込み可能コピーで、レプリケーションの流れとは切り離されている。そのためテスト中もレプリケーションは止まらず、失敗しても修正して再実行できる。テスト対象は模擬環境ではなく実際のターゲットストレージである。

**不可逆点はカットオーバーではなく Finalize。** レプリケーションストリームはテストとカットオーバーの操作から独立しており、明示的に Finalize するまで止まらない。したがってカットオーバー後もソースは同期済みのまま安全網として残る。

**自動バックアップが Finalize を阻害する理由もここにある。** バックアップが作成するロック済みスナップショットが **FlexClone の split 操作を阻む**（8.3）。バックアップはファイルシステム単位の設定なので、共用ファイルシステムでは影響範囲が同居する全ボリュームに及ぶ（5.5）。

### 9.8 他方式との性質の違いと、公開数値の扱い [文書]

**切り戻し可能な範囲の性質が方式によって違う。** どちらが優れているかではなく、要件に対する向き不向きである。

| 観点 | エージェント型（ATX / MGN） | SnapMirror ベースの経路 |
|---|---|---|
| カットオーバー前の同期 | 継続レプリケーション。テスト中も維持される | 事前同期を完了させ、切り替え時に break |
| 不可逆になる時点 | Finalize（明示操作） | break（変換の前提）。resync で回復可能だが差分転送を伴う |
| テストの反復 | FlexClone により何度でも可能 | break 前提のため、やり直しには resync が必要 |
| 向く場面 | 停止時間を最小化したい、テストを繰り返したい | 既存 ONTAP 環境で同期済みボリュームをそのまま使い、変換を速く済ませたい |

**カットオーバー停止時間**についてブログは「ソースの書き込み停止からターゲット起動までに限られ、多くのワークロードで数分」と記述している [文書]。測定条件は示されていないため、**見積りの出発点としては使えるが実測値ではない**。本検証でも未実測（U3）。

**ストレージ効率の公開数値の扱い**: ブログは移行後のデータボリュームについて「インライン重複排除 + 圧縮 + S3 への自動階層化で 65〜80% の容量削減」と記述している。ただし**対象データの性質・構成・測定方法が示されていない**。容量計画の根拠には使えない。自環境のデータで測って初めて計画値になる。同様に、移行元の一般論として挙げられている「シン・プロビジョニング、インライン重複排除、圧縮で 60〜80% 削減」も条件が示されていない。

同じ理由で、ブログの「Multi-AZ HA で自動フェイルオーバー、RPO 0」は Multi-AZ 構成を前提とした記述である。本検証環境のファイルシステムはいずれも Single-AZ であり、この特性は当てはまらない（5.1）。

## 10. FSx for ONTAP Adoption Playbook との連動

姉妹リポジトリ [FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) 側に、本 GA を反映すべき箇所がある。

### 10.1 更新が必要な既存記述

`docs/ja/reference/recent-updates.md` の「AWS Transform が FSx for ONTAP をサポート（Public Preview, 2026-06）」節は、現在 Public Preview を前提に「本番利用には GA を待つことを推奨」と記述している。GA 済みのため**この記述は古い**。更新時の要点は以下。

| 更新点 | 内容 |
|---|---|
| 状態 | Public Preview → GA（2026-08-30） |
| 推奨文 | 「GA を待つことを推奨」を削除し、9 章の制約（ブート EBS 固定・5 ファイルシステム上限・Finalize 不可逆）に置き換える |
| スコープの明確化 | 「ストレージターゲット」と「VMware データストア」を分離。後者は EVS 側であり状態が異なる |
| 出典 | What's New 2026-09 と ATX Change log 2026-08-30 を追加 |

同節の冒頭サマリー「VMware 移行パスの追加 — AWS Transform と Amazon EVS が FSx for ONTAP をストレージターゲットとしてサポート」も、2 つの経路を同一の表現でまとめている。ATX 側はストレージターゲット、EVS 側はデータストアであり、状態も GA と Public Preview で異なる。分けて書く必要がある。

### 10.2 参照すべき既存ノート

本 GA は Playbook の `03-migrate` プレイブックの範囲に入る。特に以下との関連が強い。

| Playbook のノート | 本 GA との関係 |
|---|---|
| 切り戻せる時点はクライアントが書き始めた瞬間に閉じる | ATX では Finalize が不可逆点。それ以前はロールバック可能で、レプリケーションが継続している点が SnapMirror ベースの経路と異なる |
| 移行方式の決定木 | SnapMirror / DataSync / ホスト側コピーに加えて、エージェント型 + iSCSI ターゲットという選択肢が増えた |

### 10.3 用語の対応

Playbook の evidence tier と本レポートのタグの対応は 2 章に記載した。Playbook の evidence policy は、外部リポジトリの `unverified` が `documented` へそのまま対応すると明示しており、また「ドキュメントの不在は tier ではない」と定めている。本レポートの [未確認] のうち、公開情報が存在しないもの（ONTAP バージョン要件、EVS の GA 状態）は、Playbook 側へ持ち込む際に tier ではなく本文で調査日と調査範囲を述べる形にする。

---

## 11. 未検証項目と次アクション

### 11.1 未検証項目

| # | 項目 | 状態 | 未検証の理由 |
|---|---|---|---|
| U1 | FSx for ONTAP をターゲットに指定できること | **解消**（4.4、4.5） | API とコンソール双方で実測。画面キャプチャ取得済み |
| U2 | エンドツーエンドの移行実行 | **解消**（12 章） | テストインスタンス起動からカットオーバー、**Finalize まで完了**（12.10）。データ整合性も一致 |
| U3 | 所要時間 | **解消**（12.1、12.9） | 初回フルシンク 226 秒。正しい順序でのカットオーバーは MGN ジョブ 649 秒、T0 から起動確認まで 817 秒。1 点の測定であり、構成を変えた場合は未測定 |
| U4 | LUN / ボリューム変換の実挙動 | **解消**（12.3、12.4、12.9） | 親 1 ボリューム + ディスクごとに LUN、FlexClone、igroup 2 つ、マルチパス 2 デバイスを実測。SNAPSHOT フェーズ = ボリューム Snapshot、LAUNCH フェーズ = FlexClone 作成であることを時刻で対応づけた |
| U5 | `lun move start` による移行後最適化の実挙動 | 未検証 | U2 は解消したが、移行後の `lun move` は本検証では未実行。移行直後は 1 サーバーの全 LUN が 1 ボリュームに載る（12.3）ため、復旧の粒度を分けたい場合に必要になる |
| U6 | 最小 ONTAP バージョン要件 | 未確認 | 公開ドキュメントに記載が見つからない（2026-09-04 調査） |
| U7 | EVS + FSx for ONTAP の GA 状態 | 未確認 | GA 告知が見つからない（2026-09-04 調査） |
| U8 | `SETUP_FSX_PROXY` と PrivateLink 自動確立の対応関係 | **解消**（12.2） | NLB + VPC エンドポイントサービスの作成を実測。許可プリンシパルは `mgn.amazonaws.com` |
| U9 | `initialize-service`（CLI）失敗の根本原因 | **解決** | 不具合ではない。API 経路は 8 件の IAM ロールを先に作る手順であり、それを踏んでいなかった。CloudTrail（us-east-1）に `AddRoleToInstanceProfile` の `NoSuchEntityException` が記録されている（5.4） |
| U10 | コンソールからの MGN 初期化の成否 | **解消**（5.4） | 成功。FSx 専用ロール 2 件を含む 9 ロールが作成された |
| U11 | 候補ファイルシステムの実 SSD 使用量 | **解消**（5.6） | アグリゲート 861.8 GiB / 使用 50.0 GiB / 利用率 5.8% |
| U12 | テンプレートの保存完了（FSx for ONTAP 設定の確定） | **解消**（4.6） | 証明書認証を否定対照つきで確認し、保存を API 読み戻しで確認 |
| U13 | 「追加のセキュリティグループ」必須化の公式記述 | 未確認 | コンソールの検証メッセージと画面上の説明文でのみ確認。MGN ユーザーガイドの手順記述に該当箇所が見つからない（2026-09-04 調査） |
| U14 | 証明書とログインを SVM スコープで済ませられるか | **未検証（今後の検証項目）** | 作成した SVM には独自の管理 LIF があるため成立する可能性はあるが、公式手順は管理 vserver を指定する。外すと失敗時の切り分けが困難。クラスタスコープで先に成立を確認済みなので、比較対象がある状態で試せる |
| U15 | レプリケーション実行時の ONTAP バージョン要件 | **解消**（12 章） | 9.18.1P3D1 でレプリケーションとテスト起動が成立。バージョン起因の問題は発生しなかった |
| U16 | Finalize の実挙動（FlexClone split） | **解消**（12.10） | 承認を得て実行。約 3 分後にスプリット開始、60 秒未満で完了（7.93 GiB）、約 13 分後にステージング削除。**無停止**でデータ一致。ジョブ記録は作られない |
| U18 | 正しい順序（アプリのみ停止）でのカットオーバー停止時間 | **解消**（12.9） | OS とエージェントを動かしたまま実行し、SNAPSHOT が 44 秒で成功。MGN ジョブ 649 秒、T0 から起動確認まで 817 秒 |
| U19 | `SNAPSHOT_FAIL` 時に失われる差分の範囲 | 未確認 | 本検証ではラグ 0 で書き込みも無く差分が発生しなかったため、影響を観測できていない |
| U22 | 再登録時に起動テンプレートのカスタマイズが失われる挙動の公式記述 | 未確認 | 実測では新規テンプレートが MGN 既定値で作成された（12.9）。公開ドキュメントに記述が見つからない（2026-09-04 調査） |
| U20 | ディスク割り当てを修正した後のカットオーバー成否 | **解消**（12.9） | 再登録で割り当てが整合し、起動とデータ整合性の両方が成立した。12.8 の診断が確定 |
| U21 | 割り当て不整合を MGN 側で再評価させる方法 | **解消**（2026-09-09） | `update-replication-configuration` では修復できない（矛盾する 3 種のエラー、`isBootDisk` は読み取り専用）。**正攻法はインストーラの再実行**で、[導入手順](https://docs.aws.amazon.com/mgn/latest/ug/linux-agent.html) の手順 6 が、複製対象の一覧が実機とずれた場合の修復手段として明記している。ソースサーバーの削除は不要。当方が実行した削除 + 再登録は、いちばん重い手段を選んでいた。ただし `stagingDiskType` まで再導出されるかは同記述からは決まらず未検証 |
| U17 | NLB の課金影響 | 未算出（**残存条件は判明**） | NLB は**レプリケーション期間中だけでなく Finalize 後も残る**（12.10）。手作業の撤去が必要。公開ドキュメントに記述が見つからず、費用は未見積り |
| U23 | Finalize が NLB / VPC エンドポイントサービスを残すことの公式記述 | 未確認 | 実測では T0 + 36 分まで削除されなかった（12.10）。EBS は約 33 分で削除される。公開ドキュメントに記述が見つからない（2026-09-04 調査） |

### 11.2 次アクションの候補

**エンドツーエンドは Finalize まで完了した（U2、U16、U18、U20）。** 残る未検証は次の 3 群である。

| 群 | 項目 | 進め方 |
|---|---|---|
| 実機で追加検証できる | U5（`lun move start` による移行後最適化）、U14（SVM スコープの証明書） | 本環境で試せる。U14 はクラスタスコープでの成立が比較対象になる |
| 公開ドキュメントの更新待ち | U6（最小 ONTAP バージョン）、U7（EVS の GA）、U13（追加セキュリティグループ必須化）、U22（再登録時のテンプレート再作成）、U23（Finalize が残すリソース） | 更新を待つか AWS / NetApp へ確認する。反映されるまで [未確認] のまま扱う |
| 別環境が必要 | U19（`SNAPSHOT_FAIL` 時に失われる差分の範囲）、U17（NLB の費用） | U19 は書き込みが継続するソースが必要。U17 は課金データの参照が必要 |

**移行完了後の撤去が必要である。** Finalize は片付けを完了させない（12.10）。**本検証の撤去は実施済みで、依存関係と所要時間を 13 章に記録した。** 撤去で確認すべき点は 3 つある。

- NLB と VPC エンドポイントサービスは Finalize では消えないため、手作業で削除する（13.1）
- クラスタスコープの client-ca 証明書は削除できない。**ロールの制限ではなく API がサポートしていない**（13.3）
- ターゲットインスタンスのルート EBS ボリュームは、インスタンスを終了しても残る（13.4）

共用ファイルシステムで実施した点は繰り返し確認しておく。**自動バックアップの無効化はファイルシステム全体に及ぶ**ため、本番相当の検証では専用ファイルシステムを推奨する（5.3）。ARP はボリューム / SVM 単位で制御できるため専用 SVM で隔離できる（5.5）。

---

## 12. エンドツーエンド実行結果 [実測 / 2026-09-04]

ソースサーバー（Amazon Linux 2023、ブート 8 GiB + データ 4 GiB × 2）を用意し、エージェント導入からテストインスタンス起動・カットオーバー・データ整合性確認・**Finalize** までを実行した。Finalize は不可逆であるため、承認を得てから実行した（9.1）。

途中で 2 つの失敗を経験している。読む順序としては 12.1〜12.6 が正常系、12.7 と 12.8 が失敗とその診断、12.9 が修正後の成功、12.10 が Finalize である。**結論だけ必要なら 12.9 と 12.10 を読めばよい。**

### 12.1 所要時間

| 区間 | 実測値 |
|---|---|
| 初回フルシンク（16 GiB / 3 ディスク） | **226 秒** |
| エージェント導入完了 → `READY_FOR_TEST` | 約 20 分（`CREATING_SNAPSHOT` 相当の待ちを含む） |
| テスト起動: SNAPSHOT | 43 秒 |
| テスト起動: CONVERSION | 約 4 分 30 秒 |
| 起動後に iSCSI セッションが確立するまで | 数分（直後は 0 セッション） |

最後の行は誤判定しやすい。**起動完了直後にセッション数 0 を見て失敗と判断してはいけない。**

### 12.2 SETUP_FSX_PROXY の実体

4.3 で API モデルから存在を確認し、公式ブログの「PrivateLink 接続を自動確立」に対応すると推定していた段階を、実測で確定した。この段階で**利用者の VPC 内に以下が作成される**。

| リソース | 内容 |
|---|---|
| 内部 Network Load Balancer | `MgnFSxProxy<ファイルシステム ID>NLB` |
| ターゲットグループ | `MgnFSxProxy<ファイルシステム ID>TG`、TCP/443、target type `ip`、ターゲットは **FSx 管理エンドポイントの IP**、ヘルス `healthy` |
| VPC エンドポイントサービス | 上記 NLB を公開。`AcceptanceRequired: true` |
| 接続の受理 | 許可プリンシパルに `mgn.amazonaws.com`（Service）が登録され、AWS 側アカウント所有のエンドポイントが自動的に `available` になる |

つまり MGN サービスは PrivateLink 経由で、利用者 VPC の NLB を通して ONTAP REST API（443）に到達する。管理エンドポイントを外部公開せずに済む設計である。

**費用の含意**: レプリケーション期間中、**利用者のアカウントに NLB が常駐する**。NLB の時間課金と LCU 課金が発生する。参照した AWS ドキュメントとブログにこの記述は見つからなかった（2026-09-04 調査）。移行コストの見積りに含める必要がある。

### 12.3 ストレージ構造の実測

| 対象 | 実測値 |
|---|---|
| 親ボリューム | `replication_<ソースサーバー ID>_<タイムスタンプ>`、10.00 GiB（LUN 合計 8 GiB に対して） |
| クローンボリューム | `target_<ソースサーバー ID>_<タイムスタンプ>`、`is_flexclone: true`。**LAUNCH_START の時点で作成される** |
| LUN 名 | ソースのデバイスパスを URL エンコードして保持（`{2f}dev{2f}nvme1n1` = `/dev/nvme1n1`） |
| igroup | 2 つ。`replication-<ID>`（レプリケーションサーバーの IQN）と `target-<ID>`（ターゲットの IQN） |
| LUN マップ | 各 igroup に LUN ID 0 と 1 で割り当て |
| ボリューム設定 | `guarantee: none`（シン）、`snapshot_policy: none`、効率化は `compression=inline` / `dedupe=both` / `compaction=inline` が既定で有効、`tiering: snapshot_only`（min_cooling_days 2） |

ブートディスク（8 GiB）は FSx 側に現れず、レプリケーションサーバーにアタッチされた **EBS gp3 のステージングボリューム**として存在した。「ブートは EBS、データは FSx」がストレージ層で確認できた。

### 12.4 ゲスト側の見え方とデータ整合性

テストインスタンス上での実測。

| 項目 | 実測値 |
|---|---|
| ブート | `nvme0n1` 8 GiB、`/` にマウント（EBS） |
| データ | 4 パス（`sda`〜`sdd`）→ **2 つの multipath デバイス**、`NETAPP,LUN C-Mode`、hwhandler `alua` |
| iSCSI セッション | 2 本。FSx の iSCSI エンドポイント 2 つに対して確立 |
| マルチパス優先度 | prio 50 が `active`、prio 10 が `enabled`（ALUA の optimized / non-optimized） |
| データ整合性 | **sha256 4 件すべてがソースと一致**（64 MiB ランダムデータ + マーカーファイル × 2 ディスク） |

**データディスクは自動マウントされなかった。** デバイスパスがソースの `/dev/nvme1n1` からターゲットでは `/dev/mapper/<WWID>` に変わるため、`/etc/fstab` をデバイス名で書いているとマウントに失敗する。**UUID または LABEL で記述しておく必要がある。** 本検証ではラベルでマウントして整合性を確認した。

### 12.5 遭遇した失敗と原因

いずれも公開ドキュメントに記述が見つからなかった事象である。

| # | 事象 | 表示されたエラー | 実際の原因と対処 |
|---|---|---|---|
| 1 | エージェント導入が失敗 | 「Are kernel linux headers installed correctly?」 | **カーネルヘッダは存在していた。** 真因は `No space left on device`。AL2023 の `/tmp` は RAM 由来サイズの tmpfs（t3.small で 955 MiB）で、カーネルモジュールのビルドが枯渇させた。`TMPDIR` をディスク上のパスに向けて解決 |
| 2 | テスト起動が失敗 | `VPCIdNotSpecified: No default VPC for this user` | MGN 既定の起動テンプレートは `NetworkInterfaces` にサブネットを持たず、既定 VPC へフォールバックする。既定 VPC が無いアカウントでは失敗する。テンプレートに `SubnetId` と `Groups` を明示した新バージョンを作成して解決。**この失敗は非破壊で、レプリケーションは `CONTINUOUS` / `READY_FOR_TEST` のまま維持された** |
| 3 | ターゲットが SSM に現れない | `ConnectionLost` | 起動テンプレートに IAM インスタンスプロファイルが含まれない。プロファイルを付与して復旧。ソースをキーペア無しで起動していたため SSH の代替手段が無く、切り分けの選択肢が狭まった |

1 の教訓は一般化できる。**インストーラの示すヒントが真因とは限らない。** ログの末尾ではなく、エラーコード（ここでは `NO_SPACE_LEFT_ON_DEVICE`）を確認する。

なお公式手順の Step 7 にある**「Volume integrity validation」ポストローンチアクションを有効化していなかった**。これは iSCSI 接続とマルチパスマウントを自動検証する仕組みで、12.4 を手作業で確認する代わりになる。起動前に有効化しておくべきだった。

### 12.6 未実施と残る未確認

| 項目 | 状態 |
|---|---|
| Finalize | **実施済み**（12.10）。承認を得て実行 |
| カットオーバー | **実施済み**（12.7、12.9）。データ整合性一致 |
| カットオーバー停止時間の実測 | **12.9 で再測定済み**。MGN の実作業 649 秒、T0 から起動確認まで 817 秒。12.7 の値は手順ミスを含むため製品特性として扱えない |
| `lun move start` による移行後最適化 | 未実施（U5 のまま） |
| ロールバック（revert）の実挙動 | 未実施。**Finalize 済みのため実行不可**（12.10 で拒否を確認） |
| コンソール画面のキャプチャ（本節の範囲） | 未取得。API レベルの証跡のみ |

### 12.7 カットオーバーの実測と、ジョブ成功が隠した失敗

テスト起動後にライフサイクルを `READY_FOR_CUTOVER` へ遷移させ、カットオーバーを実行した。**Finalize は実行していない。**

ライフサイクル遷移は専用 API が必要である。`start-cutover` を `TESTING` 状態で呼ぶと `ConflictException`（wrong lifecycle state）になる。`change-server-life-cycle-state` に `READY_FOR_CUTOVER` を指定して遷移させる。

#### ジョブのフェーズ内訳

| 時刻 (UTC) | 経過 | イベント |
|---|---|---|
| 09:13:45 | — | JOB_START |
| 09:13:46 | +0s | CLEANUP_START（**先行するテストインスタンスの削除**） |
| 09:14:21 | +35s | CLEANUP_END |
| 09:14:21 | +0s | SNAPSHOT_START |
| 09:19:22 | **+300s** | **SNAPSHOT_FAIL** |
| 09:19:23 | +0s | **USING_PREVIOUS_SNAPSHOT** |
| 09:22:46 | +202s | CONVERSION_END |
| 09:28:20 | +333s | LAUNCH_END |

CLEANUP が最初に走る点は、公式ブログの「新しいカットオーバーごとに、先行して起動したテストインスタンスと依存リソースを先に削除する」と一致した。

#### ジョブ成功が失敗を隠した

**ジョブは `COMPLETED` / `LAUNCHED` を返したが、最終スナップショットは失敗していた。** 300 秒でタイムアウトし、`USING_PREVIOUS_SNAPSHOT` で直前のスナップショットにフォールバックしている。ジョブのステータスだけを見ていると気づけない。

原因は本検証の手順の誤りである。停止時間を測るために**ソースの OS を停止**したが、これによりレプリケーションエージェントも停止した。MGN はクラッシュ整合スナップショットの取得にエージェントとの協調を必要とするため、到達できずタイムアウトした。

**正しい順序は、アプリケーション（書き込み）を止めて OS とエージェントは動かしたままカットオーバーする**ことである。ドキュメントの「ソースの書き込み停止からターゲット起動まで」という表現は、OS の停止を意味しない。

本検証ではデータが一致した。カットオーバー直前のラグが 0 で、マーカー書き込み後に追加の書き込みが無かったためである。しかし**書き込みが続く実環境で同じことをすると、フォールバックした分の差分が失われる**。ジョブのステータスはこのリスクを表面化しない。

**教訓**: カットオーバー後は `describe-job-log-items` を必ず確認し、`SNAPSHOT_FAIL` と `USING_PREVIOUS_SNAPSHOT` の有無を見る。ジョブが `COMPLETED` であることは、最終同期が成立した証拠ではない。

#### 停止時間の内訳

| 区間 | 実測 | 性質 |
|---|---|---|
| T0 書き込み停止（OS 停止開始） | 09:12:07 | — |
| ソース停止完了 | 09:12:54（47s） | 本検証の手順に起因 |
| `start-cutover` 発行まで | 09:13:45（+51s） | **本検証の手順ミス**（ライフサイクル遷移の未実施） |
| MGN ジョブ | 875s | うち 300s は失敗したスナップショット待ち |
| SSM 到達まで | +141s | **起動テンプレートに IAM プロファイルが無いため**（12.5 の #3） |
| T1 データ検証完了 | 09:31:29 | — |
| **合計** | **19 分 22 秒** | — |

**この 19 分 22 秒を製品の停止時間として引用してはいけない。** 内訳のうち約 8 分は本検証固有の手順ミスと構成不備（ライフサイクル遷移漏れ、失敗したスナップショット、IAM プロファイル欠如）に起因する。MGN の実作業は CLEANUP 35s + CONVERSION 202s + LAUNCH 333s = **約 9 分 30 秒**であった。

正しい順序で実施すれば、この規模（16 GiB / 3 ディスク）では 10 分前後に収まると見込まれるが、**本検証では未実測**である。公式ブログの「多くのワークロードで数分」は桁として矛盾しないが、確認できたとは言えない。

#### カットオーバー後の状態

| 項目 | 値 |
|---|---|
| ライフサイクル | `CUTTING_OVER`（Finalize 未実施のため `CUTOVER` ではない） |
| レプリケーション | `STALLED`（ソース OS を停止したためエージェント不在） |
| データ整合性 | **sha256 6 件すべて一致**。カットオーバー直前のマーカーを含む |
| ゲスト側 | iSCSI 2 セッション、multipath 2 デバイス（テスト起動時と同一） |
| ロールバック | **まだ可能**。Finalize していないため `revert` で `READY_FOR_CUTOVER` に戻せる |

### 12.8 起動不能の根本原因: デバイス名の再列挙とディスク割り当ての不整合

正しい順序でのカットオーバーを 2 回実行し、**どちらも起動不能なインスタンスが生成された**。切り分けの結果、原因はデバイス名の不安定性に起因する MGN のディスク割り当ての不整合であった。

#### 症状

ターゲットインスタンスが UEFI シェルの再起動ループに入る。

```text
No boot device
Dropping to the EFI Shell.
The system will reboot in 60 seconds.
```

UEFI のマッピングテーブルにはブート用 NVMe が 1 台見えている（データは iSCSI 接続なので UEFI からは見えず、これは正常）。**ディスクは存在するが起動可能な内容が無い。**

#### 切り分け

起動不能インスタンスのブート EBS ボリュームをデタッチし、稼働中のソースへアタッチして中身を確認した。

| 確認項目 | 結果 |
|---|---|
| パーティションテーブル | **無し**（8 GiB 全体が空きとして報告される） |
| ファイルシステム | XFS が**ローデバイスに直接**書かれている |
| ラベル | `data_nvme1n1` — **データディスクのラベル** |
| XFS のサイズ | agcount 8 × agsize 131072 blks × 4096 = **4 GiB**（8 GiB ボリューム上の 4 GiB ファイルシステム） |
| EFI システムパーティション | **無し** |

つまりブート用に用意された 8 GiB の EBS ボリュームに、**4 GiB のデータディスクの内容が書かれていた**。

#### 原因

MGN が記録しているディスク割り当てと、ソースの実際のレイアウトが食い違っていた。

| MGN の割り当て | 当該デバイスの実体（現在） | 本来の割り当て |
|---|---|---|
| `/dev/nvme0n1` → `AUTO`（EBS = ブート） | 4 GiB **データ**ディスク | FSX_ONTAP |
| `/dev/nvme1n1` → `FSX_ONTAP` | **8 GiB ブートディスク**（`/` は `/dev/nvme1n1p1`） | AUTO（EBS） |
| `/dev/nvme2n1` → `FSX_ONTAP` | 4 GiB データディスク | 正しい |

**割り当てが反転している。** 鏡像の証拠として、FSx 側の LUN サイズも変化していた。

| LUN | 初回（成功時） | 現在 |
|---|---|---|
| `/dev/nvme1n1` | 4.00 GiB | **8.00 GiB** |
| `/dev/nvme2n1` | 4.00 GiB | 4.00 GiB |

8 GiB の LUN が存在することは、**ブートディスクが FSx へレプリケートされている**ことを意味する。

原因の連鎖は以下である。

1. 停止時間を測るために**ソースインスタンスを停止・再起動した**（12.7 の手順ミス）
2. 再起動により **NVMe のデバイス名が再列挙された**。ブートディスクは `/dev/nvme0n1` から `/dev/nvme1n1` へ移動した
3. MGN の `replicatedDisks` におけるステージング種別の割り当ては**デバイス名をキーにしており、名前の移動後に再評価されなかった**
4. 結果、ブートディスクが FSx LUN へ、データディスクが EBS のブート用ボリュームへレプリケートされた
5. ターゲットに起動可能な内容が無く、UEFI シェルへ落ちる
6. **それでも MGN はジョブを `COMPLETED` / `LAUNCHED` と報告した**

テスト起動と 1 回目のカットオーバーが成功したのは、**ソースを停止する前**に実行したためである。その時点では割り当てが正しかった。

#### 一般化できる含意

これは本検証固有の事故ではなく、**実運用で起こりうる危険**である。

| 論点 | 内容 |
|---|---|
| 発生条件 | エージェント導入後にソースが再起動し、デバイス名の列挙順が変わること。NVMe では列挙順は保証されない |
| 影響 | ブートとデータのストレージ割り当てが反転し、起動不能なターゲットが生成される |
| 検知の難しさ | MGN のジョブは成功を報告する。`SNAPSHOT_FAIL` のようなログイベントも出ない |
| データ損失の有無 | 本件では発生しない（ソースは無傷、レプリケーションも継続）。ただし**移行が失敗していることに気づかないまま Finalize すると復旧手段を失う** |

**対策**:

- カットオーバー前に `get-replication-configuration` の `replicatedDisks` を確認し、**ブートディスクに対応するデバイスが `AUTO`（EBS）になっているか**をサイズと突き合わせて検証する
- `describe-source-servers` の `sourceProperties.disks` のサイズと、実機の `lsblk` を照合する
- エージェント導入後はソースを再起動しない。やむを得ず再起動した場合は割り当てを再検証する
- 公式手順 Step 7 の **Volume integrity validation ポストローンチアクション**を有効化する。起動後の検証を自動化でき、本件も早期に検知できた

12.9 で割り当てを修正して再カットオーバーを実行し、この診断を確定させた。

### 12.9 割り当て修正後のカットオーバー成功 [実測 / 2026-09-04]

12.8 の割り当て反転を修正し、正しい順序でカットオーバーを再実行して**起動とデータ整合性の両方が成立した**。12.8 の診断はこれで確定した。

#### 修正手段の選択

`update-replication-configuration` では修復できなかった。`replicatedDisks` のステージング種別を変えようとすると、**互いに矛盾する 3 種類のエラーが返る**。

| 試した内容 | 返ったエラー |
|---|---|
| データディスクのみ `FSX_ONTAP` を指定 | `FSX_ONTAP requires FSX_ONTAP staging disk type for all volumes` |
| 全ディスクに `FSX_ONTAP` を指定 | `InternalServerException` |
| ブートを `EBS` 相当に指定 | `EBS cannot use FSX_ONTAP staging disk type` |

`isBootDisk` は入力フィールドとして受け付けられない（読み取り専用）。**API 経由で割り当てを直す手段が見つからなかった**ため、ソースサーバーを削除してエージェントを再導入し、登録をやり直した。

再登録後の割り当ては実際のレイアウトと整合した。

| デバイス | サイズ | `isBootDisk` | `stagingDiskType` |
|---|---|---|---|
| ブート | 8 GiB | `true` | `AUTO`（EBS） |
| データ 1 | 4 GiB | `false` | `FSX_ONTAP` |
| データ 2 | 4 GiB | `false` | `FSX_ONTAP` |

#### 再登録の副作用: 起動テンプレートの再作成

**再登録により起動テンプレートが新規に作成され、12.5 の #2 で入れたサブネット指定と #3 の IAM プロファイル対応が失われた。** ソースサーバーを削除すると、それに紐づく起動テンプレートも切り離される。新しいテンプレートは MGN の既定値で作られるため、既定 VPC が無いアカウントでは `VPCIdNotSpecified` が再発する。

**再登録は「エージェントを入れ直すだけ」ではない。** 起動設定のカスタマイズは、再登録のたびにやり直す必要がある。

#### カットオーバー前の照合（今回追加した確認手順）

12.8 の再発を防ぐため、カットオーバー発行前に次を照合した。この照合は公式手順に含まれていないが、**入れる価値がある**。

1. `get-replication-configuration` の `replicatedDisks` から、`isBootDisk: true` のデバイスと、その `stagingDiskType`
2. `describe-source-servers` の `sourceProperties.disks` から、同じデバイス名のサイズ
3. ソース実機の `lsblk` 出力

ブートに対応するデバイスのサイズが 8 GiB で、その `stagingDiskType` が `FSX_ONTAP` ではないことを確認してから発行する。

#### ジョブのフェーズ内訳

T0（`start-cutover` 発行）= 12:04:57 UTC。**ソースの OS とエージェントは動かしたまま**、アプリケーションの書き込みが無い状態で実行した。

| 時刻 (UTC) | T0 からの経過 | イベント |
|---|---|---|
| 12:04:59 | +2s | JOB_START |
| 12:05:00 | +3s | SNAPSHOT_START |
| 12:05:44 | +47s | SNAPSHOT_END（**44 秒で成功**） |
| 12:05:45 | +48s | CONVERSION_START |
| 12:10:09 | +312s | CONVERSION_END（264 秒） |
| 12:10:10 | +313s | LAUNCH_START |
| 12:15:47 | +650s | LAUNCH_END（337 秒） |
| 12:15:48 | +651s | JOB_END |

**`SNAPSHOT_FAIL` と `USING_PREVIOUS_SNAPSHOT` は出ていない。** 12.7 で 300 秒のタイムアウトを起こした区間が、44 秒で正常終了した。差分はソースの OS を止めなかったこと以外に無い。12.7 の原因診断（エージェント不在）はこれで裏付けられた。

**CLEANUP フェーズが無い。** 12.7 では先行するテストインスタンスの削除に 35 秒を要したが、ソースサーバーを削除して再登録したため削除対象が無かった。

#### T0 から検証完了まで

| 区間 | 実測 | 性質 |
|---|---|---|
| MGN ジョブ（JOB_START → JOB_END） | **649 秒** | 製品の実作業 |
| LAUNCH_END → インスタンスステータス `ok`/`ok` | 167 秒 | OS の起動待ち |
| T0 → 起動確認完了 | **817 秒（13 分 37 秒）** | — |
| T0 → データ整合性確認完了 | 約 15 分 | 手作業のマウントと sha256 を含む |

12.7 の 19 分 22 秒との差のうち、300 秒は失敗したスナップショット、51 秒はライフサイクル遷移漏れである。**16 GiB / 3 ディスクの規模で、MGN の実作業は約 11 分**であった。この数値は 1 回の実測であり、ディスク構成・サイズ・リージョンを変えた場合の挙動は未測定である。

#### 起動の成立

| 確認項目 | 結果 |
|---|---|
| インスタンスステータス | `ok` / `ok`（12.8 の起動不能インスタンスは到達しなかった） |
| ルートデバイス | `/dev/sda1` → ゲストからは `nvme0n1`、8 GiB gp3 EBS |
| パーティション | `nvme0n1p1`（XFS、`/`）、`p127`（BIOS Boot）、`p128`（vfat、`/boot/efi`） |
| コンソール出力の異常 | `No boot device` / `EFI Shell` / `Boot Failed` は **0 件** |
| SSM | LAUNCH_END の約 3 分後に `Online` |

12.8 で欠落していた EFI システムパーティションとパーティションテーブルが、いずれも存在した。

#### データ整合性

ソース側で事前に記録した sha256 と、ターゲット上で再計算した値を突き合わせた。

| ファイル | 内容 | 一致 |
|---|---|---|
| `payload.bin`（64 MiB） | 初回フルシンク前に作成 | 両ディスクで一致 |
| `marker.txt` | 初回フルシンク前 | 両ディスクで一致 |
| `cutover.txt` | 1 回目のカットオーバー直前 | 両ディスクで一致 |
| `delta.bin`（32 MiB） / `delta.txt` | 差分同期の確認用 | 両ディスクで一致 |
| `retry.bin`（16 MiB） / `retry.txt` | 再カットオーバー前 | 両ディスクで一致 |

**14 ファイルすべて、事前記録した 8 件のハッシュすべてが一致した。**

ゲスト側の見え方は 12.4 と同じである。iSCSI セッション 2 本、multipath デバイス 2 個、`NETAPP,LUN C-Mode`、hwhandler `alua`、prio 50 が `active` / prio 10 が `enabled`。XFS ラベル（`data_nvme1n1` / `data_nvme2n1`）はソースから保持されていた。

`iscsid` と `multipathd` は `enabled`（自動起動）である。一方**データボリュームの `/etc/fstab` エントリは作成されなかった**。永続マウントの設定は移行後の作業として残る。

#### FlexClone による起動: SNAPSHOT / LAUNCH フェーズの実体

ONTAP 側を照合して、MGN のフェーズ名がどの ONTAP 操作に対応するかを確定した。

| MGN のフェーズ | 対応する ONTAP の操作 | 実測 |
|---|---|---|
| SNAPSHOT | ステージング FlexVol の **ボリューム Snapshot** 作成 | 12:05:05 UTC に作成。SNAPSHOT_START〜END の区間内 |
| LAUNCH | その Snapshot からの **FlexClone 作成** | ターゲット FlexVol の作成時刻 12:10:41 UTC |

ターゲットボリュームは `is_flexclone: true` で、`parent_volume` はステージングボリューム、`parent_snapshot` は上記 Snapshot であった。ステージングボリューム側は `has_flexclone: true` になっている。

| 項目 | 実測値 |
|---|---|
| `split_estimate` | 8,517,623,808 バイト（約 7.93 GiB） |
| `split_initiated` | `false`（起動時点でスプリットは走っていない） |
| `inherited_savings` | 2,326,528 バイト |

**含意は 2 つある。**

第一に、**SNAPSHOT フェーズはコピーではなくメタデータ操作**であり、8 GiB のデータに対して 44 秒だった。EBS スナップショットを取る経路と異なり、データ量に対する伸び方が緩やかであることが期待できる。ただし**本検証は 1 点の測定**であり、データ量を変えたときの伸び方は未測定である。

第二に、**ターゲットボリュームはステージングボリュームの Snapshot に依存している**。起動直後の物理消費は差分のみで、両ボリュームの `space.used`（それぞれ約 7.9 GiB）は論理値である。この依存関係があるため、**Finalize がステージングボリュームを削除するには FlexClone をスプリットするか削除順序を制御する必要がある**。スプリットは約 7.93 GiB の書き込みを伴う。**この予測は 12.10 で実測と一致した**（U16 解消）。

#### ONTAP 側のリソース命名（実測）

| 対象 | 命名 |
|---|---|
| ステージング FlexVol | `replication_<ソースサーバー ID をアンダースコア化>_<YYYYMMDD>_<HHMMSS>_<マイクロ秒>` |
| ターゲット FlexVol | `target_<ソースサーバー ID をアンダースコア化>_<YYYYMMDD>_<HHMMSS>` |
| LUN | `/vol/<FlexVol 名>/{2f}dev{2f}<デバイス名>`（`/` を `{2f}` として保持） |
| igroup（レプリケーション側） | `replication-<ソースサーバー ID>`。イニシエータ IQN に**レプリケーションサーバーの EC2 インスタンス ID** が入る |
| igroup（ターゲット側） | `target-<ソースサーバー ID>`。イニシエータ IQN はソースサーバー ID 由来で、インスタンス ID に依存しない |
| iSCSI ターゲット | SVM ごとに 1 つ。FSx の iSCSI LIF は HA ペアの各ノードに 1 つずつ（計 2 つ） |

FlexVol は LUN 合計 8 GiB に対して 10 GiB で作成された。`guarantee: none`（シン）、`snapshot_policy: none`、`efficiency.compression: inline`、`security_style: unix`。LUN の `os_type` は `linux`、`space.used` は 4 GiB のうち 4,247,678,976 バイト（98.9%）である。

アグリゲートは 861.8 GiB のうち 70.5 GiB 使用（8.2%）であった。5.6 の測定時（50.0 GiB）からの増分は、**共用ファイルシステムであるため本検証のみに帰属させられない**。

FlexClone の物理消費は論理値と大きく異なる。Finalize 直前の実測値である。

| ボリューム | 論理（`space.used`） | 物理（`space.physical_used`） |
|---|---|---|
| ステージング（親） | 8,533,684,224（7.95 GiB） | 8,628,998,144（8.03 GiB） |
| ターゲット（FlexClone） | 8,496,549,888（7.91 GiB） | **37,236,736（35.5 MiB）** |

**クローンは論理 7.91 GiB に対して物理 35.5 MiB しか消費していない。** 容量計画では論理値ではなく物理値を見る必要がある。この関係は Finalize で反転する（12.10）。

### 12.10 Finalize の実挙動 [実測 / 2026-09-04]

**承認を得て Finalize を実行した。** U16 の未確認事項が解消し、9.1 の記述が実測で裏付けられた。

#### 呼び出し直後の状態遷移

| 項目 | 変化 |
|---|---|
| ライフサイクル | `CUTTING_OVER` → **`CUTOVER`**（API レスポンスの時点で完了） |
| データレプリケーション | `CONTINUOUS` → **`DISCONNECTED`**（同時） |
| ジョブ記録 | **作成されない** |

**Finalize には対応するジョブが作られない。** カットオーバーやテスト起動と異なり `describe-jobs` に現れず、`describe-job-log-items` でフェーズを追うこともできない。後続のクリーンアップは非同期に進むため、**進捗はリソースの状態を直接ポーリングして判定するしかない**。

#### クリーンアップの時系列

T0 = 12:36:23 UTC（`finalize-cutover` 発行）。30 秒間隔でポーリングした。

| T0 からの経過 | 観測した変化 |
|---|---|
| 即時 | ライフサイクル `CUTOVER`、レプリケーション `DISCONNECTED` |
| 約 3 分 | **FlexClone のスプリット開始**（`split_initiated: true`）。ターゲットの物理消費が 35.5 MiB → 3.94 GiB へ上昇中 |
| 約 4 分 | **スプリット完了**（`is_flexclone: false`）。物理消費 8.57 GiB |
| 約 13 分 | ステージング FlexVol **削除**、レプリケーションサーバー EC2 **終了**、ステージング EBS が `available` へ |
| 約 23 分 | EBS ボリューム 1 本 **削除** |
| 約 33 分 | 残る EBS ボリューム 2 本 **削除**。クリーンアップ完了 |

スプリット本体は 30 秒間隔のサンプリングの間に完了しており、**7.93 GiB に対して 60 秒未満**であった。一方、スプリット完了からステージングボリューム削除までに**約 9 分の間隔がある**。

**クリーンアップは約 33 分かけて段階的に進む。** EBS ボリュームは `available` になった後、約 10 分間隔で削除された（CloudTrail の `DeleteVolume` イベントで確認）。

> **観測窓に関する補足**: 当初 T0 から 16 分だけ観測し、`available` のまま残った 3 本を「Finalize は EBS を削除しない」と記録した。**これは誤りであった。** 33 分後に再確認して全数が削除済みであることを確認し、CloudTrail で削除時刻を特定して訂正した。**非同期クリーンアップの残存判定には、観測窓の長さを明示する必要がある。**

#### 容量の含意: Finalize が一時的に要求するフルコピー

Finalize 前後で物理消費の関係が反転する。

| 時点 | ステージング（物理） | ターゲット（物理） | 合計 |
|---|---|---|---|
| Finalize 前 | 8.03 GiB | 35.5 MiB | 約 8.06 GiB |
| スプリット完了直後 | 8.03 GiB | 8.57 GiB | **約 16.6 GiB** |
| ステージング削除後 | — | 8.57 GiB | 8.57 GiB |

**移行データ 1 本分に相当する追加の物理容量が必要になり、本検証では約 9 分間保持された。** アグリゲートの空きが移行データ量を下回る状態で Finalize すると、スプリットが容量を圧迫する。**Finalize は「後片付け」ではなく、ピーク容量が最大になる工程である。**

ターゲットボリュームのサイズはスプリット中に 10.00 GiB から 10.19 GiB へ自動拡張された。スプリット後のターゲットは Snapshot を 0 個持ち、親への依存は完全に切れている。

#### スプリット中のデータ可用性

スプリット中もターゲットインスタンスは稼働を続けた。完了後に再確認した。

| 確認項目 | 結果 |
|---|---|
| マウント | 2 つとも維持（アンマウントされていない） |
| sha256（4 件を再計算） | **すべて一致** |
| iSCSI セッション | 2 本（変化なし） |
| multipath デバイス | 2 個（変化なし） |
| `dmesg` の I/O エラー / パスダウン / SCSI abort | **0 件** |

**スプリットは無停止で完了した。** 業務影響の観点では、Finalize は容量のリスクであって可用性のリスクではない（本検証の規模と負荷条件での観測）。

#### 不可逆性の確認

Finalize 後に `change-server-life-cycle-state` で `READY_FOR_CUTOVER` へ戻そうとすると拒否された。

```text
ConflictException: Cannot ChangeServerLifeCycleState for a CUTOVER server.
If you need to restart the migration, reinstall the Replication Agent.
```

**戻す手段はレプリケーションのやり直しだけである。** メッセージが「エージェントを再導入せよ」と示すとおり、初期同期から作り直しになる。

#### Finalize が片付けないもの

Finalize 後も残り、**課金が続くリソースがある**。

| 残ったもの | 状態 | 備考 |
|---|---|---|
| 内部 NLB（`MgnFSxProxy<ファイルシステム ID>NLB`） | `active` | 12.2 で作成されたもの。**T0 + 36 分まで観測して削除されなかった** |
| VPC エンドポイントサービス | `Available` | 同上 |
| igroup `replication-<ソースサーバー ID>` | LUN マップ 0 件で残存 | ONTAP 側の残骸 |
| ターゲット FlexVol と LUN 2 本、igroup `target-<ID>` | 稼働中 | 移行先の実体。**残すのが正しい**（撤去対象は移行完了の判断後） |

**EBS ボリュームは削除される（約 33 分後）。NLB と VPC エンドポイントサービスは残る。** MGN が作った FSx プロキシは、移行完了後も課金され続けるため**手作業の撤去が必要である**。公開ドキュメントにこの残存についての記述は見つからなかった（2026-09-04 調査）。

igroup の残骸は機能影響を持たないが、同じ SVM を再利用する場合に紛らわしい。

## 13. 撤去手順と実測 [実測 / 2026-09-04]

検証環境を撤去した。**共用ファイルシステム本体（`AVAILABLE` を維持）と他ワークストリームの SVM 4 つには手を触れていない**ことを、削除後に照合して確認した。

同様の検証を行う人が撤去でつまずかないよう、依存関係と実測の所要時間を残す。

### 13.1 削除順序と実測時間

| 順 | 対象 | 手段 | 実測 |
|---|---|---|---|
| 1 | ターゲット EC2、ソース EC2 | `terminate-instances` | 32 秒で両方 `terminated` |
| 2 | MGN ソースサーバー | `delete-source-server` | 即時。**`CUTOVER` 状態のまま削除でき、アーカイブは不要** |
| 3 | VPC エンドポイント接続 | `reject-vpc-endpoint-connections` | 即時 |
| 4 | VPC エンドポイントサービス | `delete-vpc-endpoint-service-configurations` | 即時 |
| 5 | NLB、ターゲットグループ | `elbv2 delete-load-balancer` / `delete-target-group` | 即時。リスナーは NLB と一緒に消える |
| 6 | ターゲット FlexVol | **FSx API** `fsx delete-volume` | **70 秒**。内部の LUN 2 本も一緒に削除された |
| 7 | SVM | **FSx API** `fsx delete-storage-virtual-machine` | **100 秒**。igroup とルートボリュームも一緒に削除された |
| 8 | ONTAP の `security login` | REST `DELETE /api/security/accounts/{owner-uuid}/{name}` | 即時 |
| 9 | ONTAP の client-ca 証明書 | — | **削除できなかった**（13.3） |
| 10 | レプリケーションテンプレート | `storageType` を `EBS` へ戻す | 即時 |
| 11 | 起動テンプレート、シークレット、セキュリティグループ、IAM ロール / プロファイル | 各 API | 即時。シークレットのみ 7 日の復旧期間 |
| 12 | ターゲットのルート EBS ボリューム | `delete-volume` | 即時（14.4） |

### 13.2 手作業が不要だった依存関係

撤去計画では「LUN のマップ解除 → LUN 削除 → FlexVol 削除」を想定していたが、**FSx API の `delete-volume` は LUN がマップされたまま FlexVol を削除した**。同様に `delete-storage-virtual-machine` は igroup とルートボリュームを内包して削除した。

**FSx が管理面として認識しているオブジェクトは、FSx API 側から削除するほうが手数が少ない。** MGN が ONTAP REST で直接作ったボリュームであっても、`fsx describe-volumes` に現れていれば FSx API で削除できる。

ただし igroup は FSx API に対応する概念が無く、SVM を残す場合は ONTAP REST で個別に削除する必要がある。

### 13.3 直接削除がサポートされていない証明書

`security login` は削除できたが、**client-ca 証明書の削除は拒否された**。

| 試した経路 | 結果 |
|---|---|
| REST `DELETE /api/security/certificates/{uuid}` | **403** `not authorized for that command`（code 6） |
| private CLI パススルー `DELETE /api/private/cli/security/certificate?...` | **403** 同じ |

**当初この節は原因を「`fsxadmin` の権限」と書いていた。帰属を訂正する。** ONTAP REST の [`DELETE /security/certificates` のエラー一覧](https://docs.netapp.com/us-en/ontap-restapi/delete-security-certificates-.html#error)に `Deleting this client_ca certificate directly is not supported.` と記載がある。**client_ca 証明書の直接削除は API としてサポートされていない。**

観測した文言は `not authorized for that command` なので、ロール由来の拒否と API 由来の非サポートを実測で分離したわけではない。**分離する必要もない。** どちらであっても、**「権限の強いロールを使えば消せる」という回避策は存在しない**（FSx for ONTAP で使えるロールにこの操作を許可するものは無い）。ロールを探す時間は使わなくてよい。

`security login` の削除方法にも注意点がある。`?application=http` を付けると **400** `Unexpected argument "application"` になる。クエリパラメータ無しの `DELETE /api/security/accounts/{owner-uuid}/{name}` が正しい。

**アクセスは確実に失効する。** ログイン削除後に、保存しておいたクライアント証明書で ONTAP REST API を叩く否定対照を実行し、**403 で拒否されること**を確認した（削除前は 200）。証明書が残っていても、対応する `security login` が無ければ認証は成立しない。

| 状態 | クライアント証明書での認証 |
|---|---|
| 証明書 + `security login` あり | 200 |
| 証明書のみ（`security login` 削除後） | **403** |

残る証明書は無効な残骸である。事前にインストールされていた 4 件（FSx 自身の CA 2 件、ONTAP の自己署名 1 件、SVM スコープ 1 件）は削除後も残存していることを確認済みで、**こちらの操作で他の証明書に影響は出ていない**。

**含意**: クラスタスコープの証明書を共用ファイルシステムに入れる場合、**`fsxadmin` の権限では完全に元へ戻せない**。専用ファイルシステムを使うか、残留を事前に合意する。

### 13.4 終了しても残るターゲットのルートボリューム

ターゲットインスタンスを `terminate` した後、**ルート EBS ボリューム 1 本が `available` のまま残った**。MGN が作成した起動テンプレートは、このボリュームに `DeleteOnTermination` を設定していない。

タグから追跡できる。`AWSApplicationMigrationServiceManaged` と `AWSApplicationMigrationServiceSourceServerID` が付いているため、**ソースサーバー ID で検索すれば取り残しを検出できる**。

これは 12.10 でステージング / 変換用のボリュームが自動削除されたのとは別の話である。**移行先インスタンスのルートボリュームは、インスタンスを消しても残る。**

### 13.5 意図的に残したもの

| 残したもの | 理由 |
|---|---|
| MGN のサービスロール 8 件とサービスリンクロール | 課金されない。MGN を再利用する際に再作成の手間を省ける |
| 事前に存在した client-ca 証明書 4 件 | こちらが作ったものではない |
| 共用ファイルシステムと他ワークストリームの SVM 4 つ | 検証対象外。削除後に `AVAILABLE` と SVM 4 件の存続を照合済み |
| シークレット（7 日の復旧期間つき削除） | 即時削除ではないため、7 日後に消える。復旧期間を 0 にする選択肢もあるが、誤削除の取り返しがつかなくなる |

### 13.6 撤去後の残高確認

削除の呼び出しが成功を返したことは、削除された証拠ではない。45 秒待ってから全項目を照合した。

| 項目 | 確認結果 |
|---|---|
| EC2 3 台（ソース / ターゲット / レプリケーションサーバー） | すべて `terminated` |
| `available` の EBS ボリューム | 0 |
| MGN ソースサーバー | 0 |
| レプリケーションテンプレートの `storageType` | `EBS`（削除済み SVM への参照なし） |
| NLB / ターゲットグループ / VPC エンドポイントサービス | すべて 0 |
| 検証用 SVM | 存在しない |
| 起動テンプレート / セキュリティグループ 2 つ / IAM ロール | すべて `NotFound` |
| **共用ファイルシステム** | **`AVAILABLE`（維持）** |
| **他ワークストリームの SVM** | **4 件すべて存続** |

---

## 14. References

一次情報のみを列挙する。

### AWS Transform

- [What's New: AWS Transform announces general availability of Amazon FSx for NetApp ONTAP support](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)
- [AWS Transform Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html) — 2026-08-30 のエントリ
- [Document history for the AWS Transform User Guide](https://docs.aws.amazon.com/transform/latest/userguide/doc-history.html) — August 30, 2026
- [Supported Regions for AWS Transform](https://docs.aws.amazon.com/transform/latest/userguide/regions.html)

### AWS Transform MGN

- [FSx for ONTAP configuration](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html) — 構成手順、Known limitations、Prerequisites
- [MGN Release notes](https://docs.aws.amazon.com/mgn/latest/ug/mgn-release-notes.html) — August 2026
- [What Is AWS Transform MGN?](https://docs.aws.amazon.com/mgn/latest/ug/what-is-mgn.html) — 対応リージョン
- [Storage related FAQs](https://docs.aws.amazon.com/mgn/latest/ug/Storage-Related-FAQ.html) — ターゲットストレージ種別
- [Does MGN work with...?](https://docs.aws.amazon.com/mgn/latest/ug/does-mgn.html) — FSx for ONTAP 連携時のデータフロー

### ブログ

- [Migrate VMware Storage to Amazon FSx for NetApp ONTAP using AWS Transform（AWS Storage Blog）](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/) — 移行ライフサイクル 5 段階、FlexClone の役割、ベストプラクティス、移行後の特性（9.7 / 9.8 の主要な出典）
- [Multi-Region Migration using AWS Application Migration Service（AWS Architecture Blog）](https://aws.amazon.com/blogs/architecture/multi-region-migration-using-aws-application-migration-service/) — ソース種別に Amazon EC2 を含む記述
- [Automating FSx for NetApp ONTAP Mounts with SSM and MGN Post-Migration](https://aws.amazon.com/blogs/migration-and-modernization/automating-fsx-for-netapp-ontap-mounts-with-ssm-and-mgn-post-migration/)

### Amazon EVS（データストア経路 — 別機能）

- [Run high-performance workloads with Amazon FSx for NetApp ONTAP（EVS ユーザーガイド）](https://docs.aws.amazon.com/evs/latest/userguide/fsx-ontap.html)
- [What's New: Amazon EVS now integrates with Amazon FSx for NetApp ONTAP](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-elastic-vmware-service-fsx-netapp-ontap/) — public preview 記載
- [Using Amazon Elastic VMware Service with FSx for ONTAP（FSx ユーザーガイド）](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/evs-ontap.html)

### NetApp ONTAP

- [ONTAP REST API: `DELETE /security/certificates`](https://docs.netapp.com/us-en/ontap-restapi/delete-security-certificates-.html#error) — エラー一覧に `Deleting this client_ca certificate directly is not supported.`（13.3 の帰属の出典）

### 関連リポジトリ

- [FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) — 10 章の連動対象
- [移行方式比較（本リポジトリ）](./migration-method-comparison.md)
- [AWS Transform 移行手順（本リポジトリ）](./aws-transform-migration-procedure.md)

---

*本レポートは 2026-09-04 時点の公開ドキュメントと、検証アカウント（ap-northeast-1）での実機確認に基づく。コンソールからの初期化と証明書認証、レプリケーションテンプレートへの `FSX_ONTAP` 設定保存、レプリケーション実行からカットオーバー、Finalize、撤去までを実測した（12 章・13 章）。残る未確認は 11 章にある。*
