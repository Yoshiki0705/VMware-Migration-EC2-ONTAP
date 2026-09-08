# AWS Transform / MGN の FSx for ONTAP 対応に対するフィードバック案

Amazon FSx for NetApp ONTAP をターゲットストレージとする AWS Transform for migrations（MGN）の移行を、ap-northeast-1 でエンドツーエンド（レプリケーション → テスト起動 → カットオーバー → Finalize → 撤去）に実行して得た所見を、AWS へ提出できる形に整理する。

実測の根拠はすべて [ATX FSx for ONTAP GA 検証レポート](./atx-fsxn-ga-verification.md) にある。本ドキュメントは提出用の要約であり、新しい主張は追加しない。

## 1. 提出時の前提情報

提出先ごとに宛先が異なる。

| 分類 | 提出先 |
|---|---|
| 不具合・エラーメッセージ | AWS Support（technical support case） |
| ドキュメントの記載漏れ | 各ドキュメントページの「Provide feedback」、または Support ケース |
| 機能改善要望 | Support ケースで feature request として起票、または担当 SA 経由 |

提出時に添える環境情報は以下である。**サポートケースの番号やベンダー内部の課題 ID は本リポジトリには記載しない。**

| 項目 | 値 |
|---|---|
| リージョン | ap-northeast-1 |
| ONTAP バージョン | 9.18.1P3D1 |
| ソース | Amazon EC2（Amazon Linux 2023、t3.small）、ブート 8 GiB + データ 4 GiB × 2 |
| レプリケーション方式 | エージェント型 |
| ステージング種別 | ブート `AUTO`（EBS）、データ `FSX_ONTAP` |
| 検証日 | 2026-09-04 |

## 2. 優先度順の一覧

影響の大きさで並べた。上の 3 件は**データ保全または移行の成否に直結する**。

| # | 分類 | 内容 | 影響 |
|---|---|---|---|
| F1 | 不具合相当 | 最終スナップショットが失敗しても、ジョブは `COMPLETED` / `LAUNCHED` を返す | 差分が失われたことに気づけない |
| F2 | 不具合相当 | ディスク割り当てが不整合でも、起動不能なターゲットに対してジョブは成功を返す | 移行失敗に気づかないまま Finalize すると復旧手段を失う |
| F3 | 機能不足 | 不整合になったディスク割り当てを修復する手段が無い | ソースサーバーの削除・再登録が唯一の回避策 |
| F4 | ドキュメント | API 経路の初期化ページが、冒頭でロール作成を代行すると読めるのに手順 1 で利用者に作成を求めている | API / IaC 経路で前提条件を踏み損ねる |
| D1 | ドキュメント | `SETUP_FSX_PROXY` が利用者 VPC に作成するリソースと、その課金の記載が無い | 移行コストの見積りが実態と合わない |
| D2 | ドキュメント | Finalize が NLB と VPC エンドポイントサービスを残すことの記載が無い | 移行完了後に課金が続く |
| D3 | ドキュメント | Finalize が一時的に要求する物理容量の記載が無い | 空き容量不足で失敗する余地がある |
| D4 | ドキュメント | 最小 ONTAP バージョンの記載が無く、稼働バージョンを AWS API から取得もできない | 事前の互換性判断ができない |
| E1 | エラーメッセージ | エージェント導入失敗時のヒントが真因と無関係 | 切り分けが長引く |
| E2 | エラーメッセージ | ステージング種別の変更が、互いに矛盾する 3 種のエラーを返す | 正しい入力を推定できない |

## 3. 不具合相当の事象

### 3.1 F1: ジョブ成功に埋もれる最終スナップショットの失敗

**事象**: カットオーバー実行時に `SNAPSHOT_FAIL` が発生し、`USING_PREVIOUS_SNAPSHOT` で直前のスナップショットにフォールバックしたにもかかわらず、ジョブは `COMPLETED`、ターゲットは `LAUNCHED` を返した。

**再現条件**: レプリケーションエージェントが応答しない状態でカットオーバーを開始する。本検証ではソース OS を停止して発生させた。スナップショットは 300 秒でタイムアウトした。

**影響**: 書き込みが継続している環境では、フォールバックした分の差分が失われる。**ジョブのステータスにはこのリスクが現れない。** `describe-job-log-items` を個別に確認しないと気づけない。

**構造上の理由**: [`Job`](https://docs.aws.amazon.com/mgn/latest/APIReference/API_Job.html) の `status` は Valid Values が `PENDING | STARTED | COMPLETED` の 3 値で、失敗を表す値を持たない。工程の成否は同じ階層に現れない。失敗を運ぶのは [`ParticipatingServer`](https://docs.aws.amazon.com/mgn/latest/APIReference/API_ParticipatingServer.html) の `launchStatus`（`PENDING | IN_PROGRESS | LAUNCHED | FAILED | TERMINATED`）で、こちらは起動の成否のみを表す。**スナップショットのフォールバックはどちらのフィールドにも現れない。** したがって「ジョブが `COMPLETED`」は仕様どおりの応答であり、リスクを表現する場所が無いこと自体が要望の対象になる。

**要望**: 最終スナップショットが失敗してフォールバックした場合、ジョブレベルで警告または非成功のステータスを返す。少なくとも `describe-jobs` のレスポンスにフォールバックの有無を示すフィールドを追加する。

### 3.2 F2: 検知されないディスク割り当ての不整合

**事象**: ブートディスクに `FSX_ONTAP`、データディスクに `AUTO`（EBS）が割り当てられた状態でカットオーバーが実行され、**起動不能なインスタンスが生成された**。UEFI シェルの再起動ループに入る。この間もジョブは `COMPLETED` / `LAUNCHED` を返した。

**再現条件**: エージェント導入後にソースインスタンスを停止・再起動し、NVMe デバイス名の列挙順が変わること。MGN のステージング種別の割り当てはデバイス名をキーにしており、名前の移動後に再評価されない。

**影響**: ブート用に確保された EBS ボリュームにデータディスクの内容が書かれるため、ターゲットは起動しない。**ジョブは成功を報告するため、Finalize まで進めてしまう余地がある。**

**要望**:

- 起動前に、`isBootDisk: true` のディスクに `FSX_ONTAP` が割り当たっていないことを検証し、不整合ならジョブを失敗させる
- ディスクのサイズと `isBootDisk` の対応が、レプリケーション開始時点から変化していないかを検知する
- Volume integrity validation ポストローンチアクションを、FSx for ONTAP ターゲットでは既定で有効にする

### 3.3 F3: 不整合になった割り当ての修復手段の不在

**事象**: `UpdateReplicationConfiguration` で `replicatedDisks` のステージング種別を修正できない。`isBootDisk` は入力として受け付けられない（読み取り専用）。

**回避策**: ソースサーバーを削除してエージェントを再導入する。これはレプリケーションを最初からやり直させる。

**要望**: 割り当てを再評価させる API、または既存の設定を実機のレイアウトに同期させる操作を用意する。それが設計上不可能であれば、**再登録が唯一の手段であることをドキュメントに明記する**。

### 3.4 F4: API 初期化ページにある前提条件を打ち消す記述

> **訂正 2026-09-08**: 当初これは「CLI の初期化が再現性をもって失敗する不具合」として提出していた。**不具合ではない。** API 経路は 8 件の IAM ロールを利用者が先に作る手順であり、それを踏んでいなかった。不具合報告としては取り下げ、ドキュメントの不整合として残す。

**事象**: [Initializing AWS Transform MGN with the API](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html) は冒頭で初期化の説明として "The required IAM roles and policies will be created." と書いている。同ページの手順 1 は "Create the required IAM roles." であり、8 件のロールを利用者が `CreateRole` で作成して管理ポリシーをアタッチすることを求めている。前者だけを読むと、`initialize-service` がロールまで作ると理解できる。

**実際の挙動**（自環境の CloudTrail、us-east-1、2026-09-03 20:31 UTC）: `initialize-service` は `CreateRole` を 1 度も呼ばない。`CreateServiceLinkedRole` → `CreateInstanceProfile` × 4 → `AddRoleToInstanceProfile` × 4 の順で呼び、後者 4 件が `NoSuchEntityException`（`The role with name AWSApplicationMigration...Role cannot be found.`）で失敗する。同ページ後半の記述と一致している。

**影響**: 前提条件を踏まずに実行すると `ValidationException: Failed to create SLR or instance profiles`（reason `OTHER`）で失敗する。エラーはどのロールが無いのかを示さないため、ページ冒頭の記述を前提にしていると、サービス側の不具合と誤診する。**実際に誤診した。**

**要望**: 1. 冒頭の "The required IAM roles and policies will be created." を、コンソール経路の説明であることが分かる形にする（API 経路は手順 1 が利用者側の作業である）。2. `ValidationException` のメッセージに、不足しているロール名を含める。

## 4. ドキュメント記載の不足

### 4.1 D1: `SETUP_FSX_PROXY` が作成するリソースと課金

**現状**: 公式ブログは「PrivateLink 接続を自動確立する」と述べているが、**利用者の VPC 内に何が作成されるかの記載が見つからない**。

**実測**: 内部 Network Load Balancer、ターゲットグループ（TCP/443、ターゲットは FSx for ONTAP の管理エンドポイント IP）、VPC エンドポイントサービス（許可プリンシパルは `mgn.amazonaws.com`）が作成される。

**要望**: 作成されるリソースの一覧と、**NLB の時間課金および LCU 課金が利用者アカウントに発生する**ことを記載する。移行コストの見積りに必要な情報である。

### 4.2 D2: Finalize が残すリソース

**実測**: Finalize から約 33 分でステージング / 変換用の EBS ボリュームは自動削除される。一方、**NLB と VPC エンドポイントサービスは T0 + 36 分まで削除されなかった**。ソースサーバーを削除した後も、AWS 側アカウントが所有する VPC エンドポイントは `available` のままであった。

あわせて、**ターゲットインスタンスのルート EBS ボリュームは、インスタンスを終了しても残る**（`DeleteOnTermination` が設定されていない）。

**要望**: 移行完了後に手作業で削除すべきリソースの一覧を、撤去手順として記載する。または Finalize で自動削除する。

### 4.3 D3: Finalize が一時的に要求する物理容量

**実測**: Finalize は FlexClone をスプリットする。スプリット前のターゲットボリュームの物理消費は 35.5 MiB（論理 7.91 GiB）であったが、スプリット後は 8.57 GiB になった。ステージングボリュームの削除までに約 9 分あるため、**その間は移行データ 1 本分の追加物理容量が必要になる**。

**要望**: 「Finalize には移行データ量と同等の物理空き容量が一時的に必要」であることを Prerequisites に記載する。空き容量が不足する場合の挙動（失敗するのか、アグリゲートを埋めるのか）も明記されることが望ましい。

### 4.4 D4: 最小 ONTAP バージョンと、バージョン確認手段

**現状**: MGN ユーザーガイドの Prerequisites と Known limitations、MGN リリースノート、ATX の Change log、AWS Storage Blog の解説記事を確認したが、**最小 ONTAP バージョンの記載が見つからない**（2026-09-04 調査）。

**あわせての課題**: FSx for ONTAP の AWS API は ONTAP のソフトウェアバージョンを返さない。`describe-file-systems` にバージョンを示すフィールドが無く、確認には VPC 内部から ONTAP CLI または ONTAP REST API に到達する必要がある。`FileSystemTypeVersion` が `None` になるのは仕様で、[`FileSystem`](https://docs.aws.amazon.com/fsx/latest/APIReference/API_FileSystem.html) は同項目を "The Lustre version of the Amazon FSx for Lustre file system" と定義している。**代替フィールドが無い**ことが課題である。

**要望**:

- 最小 ONTAP バージョン要件を明記する。要件が無いのであれば「バージョン要件なし」と明記する
- `describe-file-systems` のレスポンスに ONTAP のバージョンを含める。バージョン依存の要件が将来ドキュメント化された場合、**現状では充足判定を AWS API だけで行えない**

### 4.5 その他の記載不足

| 項目 | 現状 | 要望 |
|---|---|---|
| 追加セキュリティグループの必須化 | コンソールの検証メッセージと画面上の説明文でのみ確認できる。ユーザーガイドの手順記述に該当箇所が見つからない | 手順に記載する |
| 移行後のマウント設定 | ターゲットではデバイスパスが `/dev/mapper/<WWID>` に変わり、`/etc/fstab` は作成されない | UUID または LABEL での記述が必要であることを記載する |
| 再登録時の起動テンプレート | ソースサーバーを削除して再登録すると、起動テンプレートが MGN 既定値で新規作成され、サブネット指定などのカスタマイズが失われる | 記載する |
| シークレット ARN の選択 | ドキュメントは `AWSApplicationMigrationServiceManaged` タグを要求するが、コンソールのドロップダウンはアカウント内の全シークレットを列挙する（タグで絞り込まれない） | ドロップダウンをタグで絞り込む。または「タグは必須だが選択肢の絞り込みには使われない」ことを記載する |
| Finalize の進捗確認 | Finalize はジョブを作成しないため `describe-jobs` に現れず、フェーズを追えない。クリーンアップは約 33 分かかる | ジョブまたはイベントを発行する。少なくとも所要時間の目安を記載する |

## 5. エラーメッセージの改善要望

### 5.1 E1: エージェント導入失敗時の誤誘導

**事象**: レプリケーションエージェントの導入が失敗し、インストーラは「Are kernel linux headers installed correctly?」と表示した。**カーネルヘッダは正しく導入されていた。** 真因はビルド用一時領域の枯渇（`No space left on device` / `NO_SPACE_LEFT_ON_DEVICE`）であった。

**背景**: Amazon Linux 2023 の `/tmp` は RAM 容量に比例する tmpfs である（t3.small で 955 MiB）。カーネルモジュールのビルドがこれを枯渇させた。`TMPDIR` / `TEMP` / `TMP` をディスク上のパスへ向けて解決した。

**要望**: 容量枯渇を検出した場合は、カーネルヘッダのヒントではなく容量不足を主たる原因として表示する。あわせて、必要な一時領域のサイズを Prerequisites に記載する。

### 5.2 E2: ステージング種別変更時の矛盾するエラー

**事象**: `UpdateReplicationConfiguration` で `replicatedDisks` を修正しようとすると、入力に応じて次の 3 つが返る。

| 入力 | エラー |
|---|---|
| データディスクのみ `FSX_ONTAP` | `FSX_ONTAP requires FSX_ONTAP staging disk type for all volumes` |
| 全ディスクに `FSX_ONTAP` | `InternalServerException` |
| ブートに EBS 相当 | `EBS cannot use FSX_ONTAP staging disk type` |

1 番目は「全ボリュームに `FSX_ONTAP` が必要」と述べ、3 番目は「EBS に `FSX_ONTAP` は使えない」と述べる。**ブートが常に EBS である仕様と併せると、1 番目の指示に従える入力が存在しない。**

**要望**: ブートディスクが常に EBS であることを前提とした、一貫した検証メッセージにする。`InternalServerException` は入力検証エラーとして扱う。

### 5.3 その他のエラーメッセージ

| 事象 | 現状のメッセージ | 要望 |
|---|---|---|
| `TESTING` 状態から `start-cutover` を呼ぶ | `ConflictException`（wrong lifecycle state） | 必要な遷移操作（`change-server-life-cycle-state` に `READY_FOR_CUTOVER`）を示す |
| 既定 VPC が無いアカウントでのテスト起動 | `VPCIdNotSpecified: No default VPC for this user` | MGN 既定の起動テンプレートにサブネットが設定されていないことを示す。または起動設定のステージングサブネットから導出する |
| ターゲットが SSM に現れない | SSM 側で `ConnectionLost` | 起動テンプレートに IAM インスタンスプロファイルが含まれないことに起因する。起動設定でプロファイルを指定できるようにする |

## 6. 機能改善要望

| # | 要望 | 根拠 |
|---|---|---|
| R1 | Volume integrity validation ポストローンチアクションを、FSx for ONTAP ターゲットでは既定で有効にする | F2 の起動不能ターゲットは、このアクションがあれば起動直後に検知できた |
| R2 | レプリケーション開始前のプリフライト検証（ネットワーク到達性、証明書認証、ディスク割り当ての整合性） | 本検証で遭遇した失敗の多くは、開始前に検出可能な性質のものであった |
| R3 | `describe-file-systems` に ONTAP バージョンを含める | D4 |
| R4 | ステージング種別の割り当てを、デバイス名ではなく安定した識別子（シリアル番号など）で管理する | F2 の根本原因はデバイス名の再列挙である |
| R5 | Finalize の進捗を追跡できるジョブまたはイベントを発行する | D2、D3 の所要時間が事前に分からない |

## 7. 期待どおりに機能した点

改善要望だけでは全体像が伝わらないため、成立した部分も記録する。

| 項目 | 実測 |
|---|---|
| 証明書認証 | クラスタスコープの client-ca 証明書と `security login` で成立。証明書なしでは 401 になる否定対照も確認 |
| ターゲットの構成 | FlexVol 内の LUN として配置され、ゲストでは DM-Multipath（ALUA、prio 50 / 10）で 2 パス構成になる。XFS ラベルはソースから保持される |
| データ整合性 | 事前記録した 8 件の sha256 がすべて一致。14 ファイルすべてで差異なし |
| スナップショットの実体 | ステージング FlexVol のボリューム Snapshot であり、8 GiB に対して 44 秒。コピーではなくメタデータ操作である |
| Finalize のスプリット | 7.93 GiB に対して 60 秒未満。**無停止**で、I/O エラーもパスダウンも観測されない |
| 撤去 | FSx for ONTAP の API 側から削除すると、FlexVol は内部の LUN ごと、SVM は igroup とルートボリュームごと削除される |
| ONTAP バージョン | 9.18.1P3D1 でレプリケーションから Finalize まで成立。バージョン起因の失敗は観測されない |

## 8. 提出時の注意

- **再現条件を必ず添える。** F1 と F2 はいずれも「特定の順序で操作した場合」に発生する。順序を書かないと再現できない
- **対照を添える。** F4 は「CLI では失敗し、コンソールでは成功する」という対照があって初めて切り分けができる
- **1 点の測定であることを明示する。** 所要時間と容量はいずれも 1 構成 1 回の実測であり、一般的な性能特性として提出しない
- **顧客名・アカウント ID・リソース ID・サポートケース番号は含めない。** 再現に必要なのは構成であって識別子ではない
