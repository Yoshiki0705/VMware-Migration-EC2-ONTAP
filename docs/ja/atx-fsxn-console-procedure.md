# 手順: MGN コンソールで FSx for ONTAP をターゲットストレージに設定する

**目的**: AWS Transform MGN のコンソールで、レプリケーションのターゲットストレージに Amazon FSx for NetApp ONTAP を指定するまでの操作手順。画面キャプチャは 2026-09-04 に ap-northeast-1 で実機取得したもの。

**最終更新**: 2026-09-04
**対象**: AWS Transform MGN（旧 AWS Application Migration Service）、FSx for ONTAP ターゲット GA 版（2026-08-30）

> **前提の確認**: 本手順は設定入力までを扱う。実際のレプリケーション実行・カットオーバー・Finalize は含まない。
>
> 設定後の移行は 5 段階（継続レプリケーション → テスト → カットオーバー → ロールバック → Finalize）で進み、**不可逆点はカットオーバーではなく Finalize** である。テストは FlexClone を使うためレプリケーションを止めずに何度でも繰り返せる。**そして Finalize は後片付けではなく物理容量が最大になる工程で、スプリットに移行データ 1 本分の追加容量が一時的に必要**（12.10）。この機構と制約の全体像は [ATX FSx for ONTAP GA 検証レポート](./atx-fsxn-ga-verification.md) の 8 章・9 章（特に 9.7）を参照。一次情報は [AWS Storage Blog](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)。

---

## 1. 画面キャプチャの取り扱い

本手順の画像は `verification/screenshots/masked/` に置く。アカウント ID・IAM ユーザー名・リソース ID・組織内の名称は取得時に置換済み。

| 区分 | 場所 | git |
|---|---|---|
| 生画像 | `verification/screenshots/raw/` | `.gitignore` で除外。コミットしない |
| 置換済み | `verification/screenshots/masked/` | コミット対象 |

置換の方式は 2 通りあり、保証の強さが違う。

| 方式 | 対象 | 保証 |
|---|---|---|
| DOM 置換 → 撮影 | 再現可能な画面 | 撮影時点で DOM に文字列が存在しない。ピクセルに含まれ得ない |
| 画像置換（`tools/redact_screenshot.py`） | 再現できない一過性の画面 | OCR の語単位バウンディングボックスを黒塗り + ヘッダ帯を無条件に塗り潰し |

検証は OCR で行い、**生画像で読めていた文字列が置換後に読めないこと**を対で確認する（対照実験がないと「OCR が読めないだけ」を「置換できている」と誤認する）。ダークテーマの画面は OCR が本文を読めないため対照が成立せず、その場合は DOM 置換の保証に依拠する。

---

## 2. 前提条件

| # | 条件 | 確認方法 |
|---|---|---|
| 1 | FSx for ONTAP ファイルシステムが `AVAILABLE` | `aws fsx describe-file-systems` |
| 2 | SVM が `CREATED` | `aws fsx describe-storage-virtual-machines` |
| 3 | MGN と FSx for ONTAP が同一アカウント・同一リージョン | — |
| 4 | ONTAP 管理エンドポイントへ VPC 内から到達可能 | VPC 内のホストから `curl -k https://<mgmt-ip>/api/cluster` が 401 を返す |
| 5 | クライアント証明書を Secrets Manager に保管済み | 後述 5 章 |

条件 5 が未了でも 4 章までは進める。設定の保存には必須。

---

## 3. サービスの初期化

MGN が未初期化の場合、`設定 → レプリケーションテンプレート` を開くとセットアップ画面へリダイレクトされる。

![MGN サービス初期化画面](../../verification/screenshots/masked/05-mgn-setup-service-init.png)

画面の説明文は「続行することで、データレプリケーションと移行済みサーバーの起動に必要なすべての IAM ロールを AWS Transform MGN が作成することを許可することになります」。`サービスをセットアップ` を押す。

> **CLI / API 経路には前提条件がある**: `aws mgn initialize-service` は IAM ロールを作らない。8 件のロールを先に作成して管理ポリシーをアタッチしてから実行する手順であり（[API での初期化](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html) の手順 1）、これを踏まずに実行すると `ValidationException: Failed to create SLR or instance profiles`（`reason: OTHER`）で失敗する。失敗時はサービスリンクロールと**ロール未紐付けのインスタンスプロファイル 4 件**が残るため、やり直す前に削除しておくと状態が読みやすい。コンソール経路はロール作成まで代行するため、前提条件なしで成功する。詳細は [検証レポート 5.4](./atx-fsxn-ga-verification.md)。

初期化が完了すると「デフォルトのテンプレートが作成されました」が表示される。

![初期化完了](../../verification/screenshots/masked/06-mgn-init-success.png)

作成されるロールを確認する。

```bash
aws iam list-roles \
  --query "Roles[?contains(RoleName,'ApplicationMigration')].RoleName" \
  --output json
```

FSx for ONTAP 対応で追加された 2 つが含まれていることを確認する。

| ロール | アタッチされる管理ポリシー | 用途 |
|---|---|---|
| `AWSApplicationMigrationFsxProxyRole` | `AWSApplicationMigrationFSxProxyPolicy` | FSx への到達経路 |
| `AWSApplicationMigrationFsxProxyLinkRole` | `AWSApplicationMigrationFSxProxyVPCPolicy` | VPC 側の接続（PrivateLink） |

この 2 ロールが無い場合、FSx for ONTAP をターゲットにしても動作しない。初期化が FSx for ONTAP 対応前に行われた環境では、レプリケーションテンプレート画面の `サービスのアクセス許可を再初期化` を実行する。

---

## 4. ターゲットストレージの選択

`設定 → レプリケーションテンプレート` を開く。初期状態の `Default Storage Provider` は `EBS`。

![レプリケーションテンプレート（既定は EBS）](../../verification/screenshots/masked/07-mgn-replication-template-ebs.png)

`編集` を押し、`Storage configuration` セクションまでスクロールする。選択肢は 2 つ。

| タイル | 画面上の説明 |
|---|---|
| EBS (Elastic Block Storage) | EC2 に直接アタッチされる高性能ブロックストレージ |
| Amazon FSx for NetApp ONTAP | 共有ストレージや専用のファイルシステム機能を要するワークロード向け |

`Amazon FSx for NetApp ONTAP` を選ぶと、画面の表示が 3 か所変わる。

![FSx for ONTAP 選択後](../../verification/screenshots/masked/09-mgn-fsxn-selected-config.png)

| 変化 | 内容 |
|---|---|
| 注記の追加 | 「Data disks will be migrated to FSx for ONTAP. Boot disk is always migrated to EBS as required by Amazon EC2.」 |
| ラベルの変更 | 「EBS ボリュームタイプ（500 GiB を超えるディスクのレプリケート用）」→「EBS volume type (for boot disk)」 |
| セクションの追加 | 「Amazon FSx for NetApp ONTAP configuration」（SVM ID と Secret ARN） |

ブートディスクが EBS 固定であることは、ドキュメントの記述だけでなく**画面上でも明示される**。

### SVM の選択

`Storage Virtual Machine (SVM) ID` のドロップダウンは、リージョン内の FSx for ONTAP ファイルシステムを横断して SVM を列挙する。各項目は SVM 名 / SVM ID / 所属ファイルシステム ID（名前）の 3 段で表示される。

![SVM ドロップダウン](../../verification/screenshots/masked/10-mgn-svm-dropdown.png)

AD 参加の有無による絞り込みは行われない。AD 参加 SVM も同じ一覧に並ぶため、選択時に区別する必要がある。

### Secret ARN の選択

`FSx Storage Secret ARN` のドロップダウンは、**リージョン内の Secrets Manager シークレットを全件列挙する。絞り込みは行われない。**

![Secret ARN ドロップダウン](../../verification/screenshots/masked/11-mgn-secret-arn-empty.png)

実測では、リージョン内の 23 件すべてが候補に並んだ。うち `AWSApplicationMigrationServiceManaged` タグを持つものは 1 件だけで、**タグの無いシークレットも同じ一覧に並ぶ**。

> **検証の注意**: 当初この一覧を「タグ付きのみに絞り込まれる」と記録したが誤りだった。タグ付きシークレットを作る前に一覧が空に見えたのは、ドロップダウンの読み込み前に観測したためで、絞り込みの結果ではない。**空の描画から絞り込み規則を推定してはいけない。**

したがって、**タグや中身の形式が誤ったシークレットを選ぶことが UI 上は可能**である。タグ（`AWSApplicationMigrationServiceManaged` = `True`）とキー名（`cert` / `key`）は MGN がシークレットを扱うために公式手順が要求する条件だが、選択時には強制されない。誤りはレプリケーション開始時まで表面化しない。

選択前に自分で確認する。

```bash
aws secretsmanager list-secrets --region <region> \
  --query 'SecretList[?Tags[?Key==`AWSApplicationMigrationServiceManaged`]].Name' \
  --output json
```

---

## 5. 必須項目と検証の挙動

`Amazon FSx for NetApp ONTAP` を選んだ状態で未入力のまま `テンプレートを保存` を押すと、3 項目が必須として弾かれる。

![必須項目の検証](../../verification/screenshots/masked/12-mgn-fsxn-required-field-validation.png)

| 必須項目 | 画面のメッセージ |
|---|---|
| Storage Virtual Machine (SVM) ID | 「フィールド『Default Storage Provider』の値が『Amazon FSx for NetApp ONTAP』の場合、フィールド『Storage Virtual Machine (SVM) ID』は必須です。」 |
| FSx Storage Secret ARN | 同様に必須 |
| 追加のセキュリティグループ | 同様に必須 |

**「追加のセキュリティグループ」が必須になる点は、MGN ユーザーガイドの手順記述からは読み取れない。** コンソールで初めて分かる制約であり、iSCSI 用のセキュリティグループを事前に用意しておく必要がある。

画面の説明文には根拠が書かれている。「When using Amazon FSx as the default storage provider, the security group must also allow communication with Amazon FSx.」既定の MGN セキュリティグループが開けるのは受信 1500 のみで、FSx との通信（3260 / 443）は含まれないため、追加が要求される。

> **コンソールと API で検証の強さが違う**: API（`update-replication-configuration-template`）は `storageType=FSX_ONTAP` を**存在しないシークレット ARN のまま受理し、永続化する**。SVM ID は API でも実在確認されるが、シークレット ARN は確認されない。つまり **API 経由で設定した場合、誤りはレプリケーション開始時まで表面化しない**。IaC や CLI で設定する場合は、シークレット ARN の実在と内容を自前で検証すること。検証結果は [検証レポート 4.4](./atx-fsxn-ga-verification.md)。

---

## 6. 証明書とシークレットの作成

### 6.1 管理エンドポイントへの到達方法

管理エンドポイントは VPC 内部からのみ到達できる。踏み台に認証情報を渡すと SSM のコマンド履歴に平文で残るため、共用アカウントでは **SSM のポートフォワードでトンネルを張り、認証情報は手元から使う**方法を採る。

```bash
aws ssm start-session --target <instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<mgmt-ip>"],"portNumber":["443"],"localPortNumber":["8443"]}'
```

前提は session-manager-plugin と SSM エージェント 3.1.1374.0 以降。VPC ピアリング越しでも到達する（実測）。

### 6.2 証明書の生成

秘密鍵は PKCS#8 でなければならない。`openssl req` の既定は PKCS#1 なので変換する。

```bash
CN=mgn-fsx-client
openssl req -x509 -newkey rsa:2048 -nodes -keyout raw.key -out client.crt \
  -days 730 -subj "/CN=$CN"
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt -in raw.key -out client.key
rm -f raw.key
head -1 client.key   # -----BEGIN PRIVATE KEY----- であること
```

### 6.3 ONTAP へのインストール

REST API で実施する場合（SSH を使わずトンネル経由で完結する）。

```bash
python3 -c 'import json,pathlib; print(json.dumps({"type":"client_ca","public_certificate":pathlib.Path("client.crt").read_text()}))' > body.json
curl -sS -k -u "$U:$P" -X POST -H 'Content-Type: application/json' \
  --data @body.json https://127.0.0.1:8443/api/security/certificates

curl -sS -k -u "$U:$P" -X POST -H 'Content-Type: application/json' \
  -d '{"name":"mgn-fsx-client","owner":{"name":"<FsxId...>"},
       "applications":[{"application":"http","authentication_methods":["certificate"]}],
       "role":{"name":"fsxadmin"}}' \
  https://127.0.0.1:8443/api/security/accounts
```

ログイン名は証明書の CN と一致させる。CLI で行う場合は公式手順の `security certificate install` / `security login create` を使う。

**動作確認は否定対照を添えて行う。** 証明書ありで 200、証明書なしで 401 の両方を確認しないと、証明書が効いているのか元から通っているのか区別できない。

```bash
curl -sS -k --cert client.crt --key client.key https://127.0.0.1:8443/api/cluster
curl -s -k -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/api/cluster   # 401 であること
```

> **スコープの注意**: 公式手順の `vserver_name` はファイルシステム ID 形式（`FsxId...`）の**管理 vserver**を指す。データ SVM ではない。したがって共用ファイルシステムでは**クラスタスコープの認証追加**になる。追加のみで既存の認証は変更しない。秘密鍵を持たない者に権限は渡らない。
>
> **撤去は完全には戻せない（実測）**: `security login` は `fsxadmin` で削除できるが、**client-ca 証明書の削除は `fsxadmin` では 403 `not authorized for that command` になる**（REST の `DELETE /api/security/certificates/{uuid}` と private CLI パススルーの両方で拒否。ONTAP 9.18.1P3D1 で実測）。ログインを削除した時点で証明書認証は 403 で拒否されるため**アクセスは確実に失効する**が、証明書そのものは無効な残骸として残る。共用ファイルシステムに恒久的な残留物を作りたくない場合は、この点を事前に合意しておく。
>
> 作成した SVM には独自の管理 LIF が付くため、SVM スコープの `security login` で足りる可能性はあるが**未検証**（検証レポートの U14）。公式手順から外れると失敗時の切り分けが難しくなる。

なお FSx はクラスタスコープの client-ca 証明書を 2 件あらかじめ導入している（`FSxCAforONTAP-1in<region>` と `AmazonFSxRootCA1for<region>`）。自分で入れた証明書はこれらと併存する。

### 6.4 Secrets Manager への保管

| 条件 | 内容 |
|---|---|
| キー名 | 厳密に `cert` と `key` の 2 つ。`certificate` / `private_key` は不可 |
| 含めない項目 | `username` フィールド |
| 秘密鍵の形式 | PKCS#8 |
| タグ | `AWSApplicationMigrationServiceManaged` = `True` |

```bash
aws secretsmanager create-secret --region <region> \
  --name mgn/fsx-ontap/client-certificate \
  --secret-string file://secret.json \
  --tags Key=AWSApplicationMigrationServiceManaged,Value=True
```

保管後はローカルの秘密鍵を削除する。以降の正本は Secrets Manager 側になる。

---

## 7. 保存の完了

必須 3 項目を埋めると保存できる。

![必須項目を充足した状態](../../verification/screenshots/masked/13-mgn-fsxn-fields-populated.png)

保存後、`Default Storage Provider` が `Amazon FSx for NetApp ONTAP` になり、SVM ID と Secret ARN が表示される。

![保存後のテンプレート](../../verification/screenshots/masked/14-mgn-template-saved-fsxn.png)

**画面表示だけで判定しない。** 保存後は API で読み戻して確認する。

```bash
aws mgn describe-replication-configuration-templates --region <region> \
  --query 'items[].{id:replicationConfigurationTemplateID,storage:storageConfiguration}' \
  --output json
```

`storageType` が `FSX_ONTAP` で、`fsxOntapConfiguration` に SVM ID と Secret ARN が入っていること。SVM ID とシークレット ARN はそれぞれ `describe-storage-virtual-machines` / `describe-secret` で名前に解決して、意図した対象を指しているかまで確認する。

## 8. この手順で確認できたことと、できていないこと

| 項目 | 状態 |
|---|---|
| コンソールからのサービス初期化 | 実測・成功 |
| FSx for ONTAP 専用 IAM ロール 2 件の作成 | 実測・確認 |
| ターゲットストレージ選択 UI の存在 | 実測・確認 |
| ブートディスク EBS 固定の画面表示 | 実測・確認 |
| SVM 列挙 | 実測・確認 |
| 必須項目 3 件の検証 | 実測・確認 |
| 証明書認証（否定対照つき） | 実測・成功（証明書あり 200 / なし 401） |
| **テンプレートの保存** | **実測・成功**（API 読み戻しで確認） |
| レプリケーション実行以降 | **未実施** |

レプリケーション以降に進む場合の前提は、検証レポートの 8 章・9 章を参照。自動バックアップはファイルシステム単位の設定であり、無効化すると同居する全ボリュームに及ぶ（retention=0 は既存の自動バックアップを削除する）。ARP はボリューム単位 / SVM 既定で制御できるため、専用 SVM で隔離できる。

---

## 参考リンク

- [FSx for ONTAP configuration（MGN ユーザーガイド）](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html)
- [What's New: AWS Transform FSx for NetApp ONTAP サポート GA](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)
- [Migrate VMware Storage to Amazon FSx for NetApp ONTAP using AWS Transform（AWS Storage Blog）](https://aws.amazon.com/jp/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/) — 移行ライフサイクル 5 段階、FlexClone の役割、ベストプラクティス
- [AWS Transform Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html)
- [ATX FSx for ONTAP GA 検証レポート（本リポジトリ）](./atx-fsxn-ga-verification.md)
- [移行方式比較（本リポジトリ）](./migration-method-comparison.md)
- [SVM 数の上限（スループット容量に連動）](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-svms.html)
- [自動バックアップはファイルシステム単位の設定](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-backups.html)
- [ARP の有効化（ボリューム単位 / SVM 既定）](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/enable-ARP.html)

---

*本手順は 2026-09-04 に ap-northeast-1 で取得した実機画面に基づく。UI は変更されうるため、差異があれば公式ドキュメントを優先する。*
