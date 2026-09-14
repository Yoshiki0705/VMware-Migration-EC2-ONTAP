# ONTAP 機能を選定要素として扱う

Amazon FSx for NetApp ONTAP を容量単価だけで評価すると、**EBS に対応する手段が無い機能、
あるいは対応する手段に別の課金が付く機能**が抜け落ちます。この文書は、機能ごとに
「何ができるか」「EBS では何が必要になるか」「費用と時間にどう効くか」「制約」を並べ、
サービス選定と設計の判断材料にできる形にします。

> **費用の試算は [費用の比較](tco-comparison.md) にあります。** こちらは容量単価では
> 表せない要素を扱います。**両方を読まないと選定の判断はできません。**

## 先に結論

**階層化を前提にできない構成でも、機能面の差は残ります。** 特に効くのは
**同じデータから多数の面を作る場合**で、EBS は面の数だけ容量が増えますが、FlexClone は
親とブロックを共有するため増えません。

ゴールデンイメージ 500 GB、1 面あたり書き換え 10%、`snapshot-only`（階層化なし）:

| 面の数 | 課金対象の論理容量（FSx / EBS） | 倍率 | FSx 月額 | EBS 月額 |
|---|---|---|---|---|
| 0 | 500 / 500 GB | 1.00 | $1,080.83 | $73.00 |
| 10 | 1,000 / 5,500 GB | 5.50 | $1,080.83 | $553.00 |
| 20 | 1,500 / 10,500 GB | 7.00 | $1,080.83 | $1,033.00 |
| **30** | 2,000 / 15,500 GB | 7.75 | **$1,080.83** | $1,513.00 |
| 50 | 3,000 / 25,500 GB | 8.50 | **$1,111.13** | $2,473.00 |

**面が少ないうちは EBS が安く、30 面で逆転します。** ただし EBS 側で
**Fast Snapshot Restore を有効にすると、10 面でも逆転します**（下記）。

**1 面あたりの書き換えを 10% としたのは、NetApp が公表している例から逆算した値です。**
本番データベース 100 GB に完全ミラー 1 本と開発 / テスト 6 コピーを持つ場合、通常は
合計 800 GB になるところ、DevTest のコピーに FlexClone を使うと 260 GB に収まり、
**削減率は 67%** とされています
（[出典](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)）。
差の 60 GB を 6 コピーで割ると 1 本あたり 10% です。**これは NetApp の公表例で、
このプロジェクトの実測値ではありません。**

### ブロックストレージでも成立する理由

**この差は階層化に依存しないので、ブロックでも成立します。** AWS が明記しているのは
ボリューム単位のクローンですが、
[LUN はボリュームの中に置かれる](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/create-iscsi-lun.html)ため、
ボリュームをクローンすれば LUN も一緒にクローンされます。

**未確認**: `lun clone` や file clone を FSx for ONTAP で単体で使えるかは確認していません。
NetApp の記事はボリューム・LUN・ファイルのコピーが可能と説明していますが、
**AWS のドキュメントで確認できたのはボリューム単位のクローンまでです。**

## 構成パターン

NetApp の記事に示された 2 つのワークフローと配置図をもとに、構成として整理します
（[出典](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)。
図そのものは転載せず、内容を構成として書き直しています）。

### パターン A: アプリケーション開発（Clone → Test → Reiterate）

| 段階 | 操作 | 効くところ |
|---|---|---|
| Clone | 本番データセットのシンクローンを作成 | 容量を消費せず、待ち時間が作成時間だけになります |
| Test | 本番に影響を与えずに実データでテスト | **本番と同じデータで試せます。** サンプルデータで代替する必要がありません |
| Reiterate | クローンを作り直して最新データで反復 | **古いデータでテストし続ける状態を避けられます** |

**回すたびにクローンを捨てて作り直すのが前提です。** 分離（split）すると共有をやめるので、
容量の利点も失われます。

### パターン B: ディザスタリカバリ（Mirror → Test → Activate）

| 段階 | 操作 | 効くところ |
|---|---|---|
| Mirror | SnapMirror で二次側へ複製 | RPO 5 分、RTO 数分 |
| Test | **複製を止めずに DR コピーを検証** | DR 先のボリュームをクローンして検証するため、SnapMirror は親への複製を続けます |
| Activate | 障害時に二次側へフェイルオーバー | — |

**「検証のために複製を止める」が不要になる点がこのパターンの要点です。**
[S&P Global の事例](https://aws.amazon.com/blogs/architecture/sp-globals-innovative-disaster-recovery-strategy-using-amazon-fsx-for-netapp-ontap-snapshots/)は
この形で、FlexClone の作成が 2 分未満だと報告されています。

### クローンの成り立ち（3 層）

NetApp の図は、クローンを次の 3 層として説明しています。

| 層 | 内容 |
|---|---|
| Active volume | クローン元の現用ボリューム |
| Snapshot | そのボリュームの時点イメージ。**クローンの土台になります** |
| FlexClone | Snapshot の前に置かれた**書き込み可能な透過レイヤー** |

**クローンは土台のスナップショットに依存します。** AWS の API にも
「宛先ボリュームのスナップショットクローン」を削除する `DELETE_CLONED_VOLUMES` オプションが
あり、クローンとスナップショットが結び付いていることが読めます。
**土台のスナップショットを消す運用を設計に入れないでください。**

### 配置と、そこから来る費用

NetApp の配置図は、一次側に Parent（Prod）と Clone1（Dev）・Clone2（QA）を同じアグリゲート上に、
二次側に DR Replica と DR Clone を別のアグリゲート上に置く形を示しています。
**ここから 2 つの設計上の帰結が出ます。**

**1. Dev / QA のクローンは一次側の確保済みリソースを分け合います。** AWS は SSD 減設が
FlexClone で止まる理由を「ONTAP がボリューム移動時にクローン関係を分割し、新しいディスク上で
容量が二重になるため」と説明しています
（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ssd-decrease-troubleshooting.html)）。
つまりクローンは親と同じディスクを共有しており、**SSD 容量・IOPS・スループット容量は
一次側のファイルシステムのものを分け合います。** クローンは親の QoS を継承しないので、
**面を増やすときは QoS ポリシーグループで束ねてください。**

**2. 二次側は別のファイルシステムなので、最小 SSD とスループット容量が独立に乗ります。**
親 2,048 GB、差分 10%、512 MB/s、階層化なしの場合:

| 構成 | 一次側 | 二次側 | 合計 |
|---|---|---|---|
| 二次側 Single-AZ | $1,080.83 | $617.47 | **$1,698.30** |
| 二次側 Multi-AZ | $1,080.83 | $1,080.83 | **$2,161.66** |

**二次側の内訳は SSD 1,024 GiB が $153.60、スループット容量が $463.87 で、
スループットが 75% を占めます。** DR クローンの容量が小さくても、この 2 つは減りません。
**「クローンは容量を消費しないから DR は安い」とは言えません。**

## 機能ごとの選定要素

### FlexClone — 容量を消費しない書き込み可能な複製

**クローンは親とブロックを共有し、共有している分の容量を消費しません**
（[FSx の機能](https://aws.amazon.com/fsx/netapp-ontap/features/)）。書き換えた分だけが増えます。

| 観点 | 内容 |
|---|---|
| EBS で対応する手段 | スナップショットから新しいボリュームを作る。**面の数だけ全容量が課金されます** |
| 作成時間 | AWS が公開している DR 事例では **2 分未満**（[S&P Global の事例](https://aws.amazon.com/blogs/architecture/sp-globals-innovative-disaster-recovery-strategy-using-amazon-fsx-for-netapp-ontap-snapshots/)） |
| EBS 側の「すぐ全性能」の費用 | **Fast Snapshot Restore が必要**。スナップショット × AZ × 時間で課金され、東京では 1 スナップショット × 1 AZ で月 $648 相当（$0.90/時 × 720 時間）。有効にしない場合は遅延読み込みで、初期化まで性能が落ちます（[出典](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-fast-snapshot-restore.html)） |
| **制約 1** | **クローンは親の QoS 上限を継承しません。** 30 人の開発者が 30 クローンを作ると本番に影響しうるので、QoS ポリシーグループで束ねる必要があります（[出典](https://aws.amazon.com/blogs/storage/using-quality-of-service-in-amazon-fsx-for-netapp-ontap/)） |
| **制約 2** | **SSD 減設中にクローンを作ると減設が止まります。** ONTAP がボリューム移動時にクローン関係を分割するためで、クローンを削除するまで再開しません（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ssd-decrease-troubleshooting.html)） |
| 制約 3 | ボリューム数の上限（第一世代 500）が面の数の上限になります |
| **制約 4** | **クローンを親から分離（split）すると追加のディスク容量が必要になります。** 共有をやめる操作なので、容量の利点も失われます |
| 自動化 | ONTAP REST API / CLI で作成できるため、**CI/CD パイプラインに組み込めます** |

**効くのはこういう場面です。** 開発・テスト・ステージング・スキーマ検証を同じ本番データから
作る場合、DR 環境を本番の複製として持つ場合、リリース前の検証を本番相当データで行う場合。
**面の数が増えるほど差が開きます。**

**DR との組み合わせが特に効きます。** DR 先のボリュームをクローンして検証している間も、
SnapMirror は親ボリュームへの複製を続けます。**検証のために複製を止める必要がありません**
（[NetApp](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)、
[S&P Global の事例](https://aws.amazon.com/blogs/architecture/sp-globals-innovative-disaster-recovery-strategy-using-amazon-fsx-for-netapp-ontap-snapshots/)）。

**開発サイクルへの効き方**として、NetApp はゲーム開発企業の事例を挙げています。新しい
インスタンスへソースコードを渡す時間が数時間から数分になり、数百インスタンスの並列テストで
テストコピーごとの容量課金が不要になったとされています
（[出典](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)）。
**社名は公表されておらず、こちらの実測でもありません。**

### Snapshot — 変化した分だけを消費する時点イメージ

| 観点 | 内容 |
|---|---|
| 課金 | **追加料金では課金されず、確保済みの SSD を消費します。** 変化した部分だけを消費します |
| EBS で対応する手段 | EBS Snapshot。**S3 に保存され $0.05/GB-月**（アーカイブ $0.0125/GB-月、取り出し $0.03/GB） |
| 制約 | **スナップショットはバックアップに含まれません。** バックアップとは別に考える必要があります |

### SnapMirror — ボリューム単位の複製と DR

| 観点 | 内容 |
|---|---|
| できること | リージョン内・リージョン間の複製。**RPO 5 分、RTO 数分**（[FSx の機能](https://aws.amazon.com/fsx/netapp-ontap/features/)） |
| EBS で対応する手段 | スナップショットのコピー、またはアプリケーション側の複製。**ブロックレベルの複製は自分で作ります** |
| **制約 1** | **ボリューム単位のみ。SVM DR（SVMDR）は非対応** |
| **制約 2** | **同期 SnapMirror（StrictSync を含む）は非対応。** RPO 0 は取れません（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/scheduled-replication.html)） |
| 組み合わせ | DR 先で FlexClone を作れば、**複製を止めずに検証できます**（上記 S&P Global の事例） |

### FlexCache — 読み取り中心の分散アクセス

| 観点 | 内容 |
|---|---|
| できること | 必要な分だけを取得するスパースなキャッシュ。オンプレ ↔ FSx、FSx ↔ FSx の組み合わせが可能 |
| 向く条件 | **読み取り中心で、変更が少ないワークロード。** 変更があるとキャッシュの更新が必要です |
| EBS で対応する手段 | 該当なし（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)） |

### マルチプロトコル — 同じボリュームへの NFS / SMB / iSCSI / NVMe

| 観点 | 内容 |
|---|---|
| できること | 同じデータに複数のプロトコルで到達できます。移行後の再配置（EC2 → ECS / EKS など）でデータ層を変えずに済みます |
| EBS で対応する手段 | **該当なし。** 共有アクセスには別のサービスが必要で、Multi-Attach は同一 AZ・io1/io2 限定・ブート不可・クラスタファイルシステム必須です |

### ストレージ効率化 — 圧縮・重複排除・コンパクション

| 観点 | 内容 |
|---|---|
| 公表代表値 | **仮想サーバー / 仮想デスクトップで 70%**（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html)） |
| EBS で対応する手段 | 該当なし |
| **制約** | **後処理圧縮は ONTAP で既定無効**（性能影響のため）。有効化に診断権限が必要で、**公表値をそのまま前提にできません** |

### SnapLock — WORM による改変防止

| 観点 | 内容 |
|---|---|
| できること | 指定期間の改変・削除を防止。リーガルホールドも可能 |
| EBS で対応する手段 | 該当なし。**スナップショットのロックや IAM での制御は、ボリューム内のファイル単位の WORM とは別物です** |
| 補足 | SnapLock ボリュームでも容量プールへの階層化は可能 |

### QoS — ボリューム単位の IOPS / スループット上限

| 観点 | 内容 |
|---|---|
| できること | ポリシーグループで上限を設定。共有・非共有を選べます |
| EBS で対応する手段 | ボリュームごとに確保するので、**上限は設定ではなく購入で決まります** |
| **制約** | **クローンは親のポリシーを継承しません**（FlexClone の制約 1 と同じ） |

### バックアップ

| 観点 | 内容 |
|---|---|
| できること | ボリューム単位の日次自動バックアップ。増分・クラッシュ整合 |
| 課金 | 消費量課金 |
| **制約** | **ボリューム削除時に最終バックアップが既定で取られ、残ると課金が続きます**（[撤去手順](quickstart.md#スタック削除)） |

## 選定と設計での使い方

**次の順で判断してください。**

| 段階 | 問い | 決まること |
|---|---|---|
| 1 | 面をいくつ作るか（開発 / テスト / DR / 検証） | **FlexClone が効くかどうか。面が多いほど FSx 側に寄ります** |
| 2 | ブロックのまま持っていくか、ファイルに置き換えるか | 階層化と効率化が効くかどうか。[階層化前提の不成立](tco-comparison.md#ブロックストレージにおける階層化前提の不成立)を参照 |
| 3 | RPO / RTO の要件 | SnapMirror で足りるか（**RPO 0 は取れません**）、EBS 側で何を作るか |
| 4 | 可用性のコミットメント | [可用性を揃えた比較](tco-comparison.md#可用性を揃えた比較9999) を参照 |
| 5 | 改変防止・監査の要件 | SnapLock が要るか。EBS に対応手段はありません |
| 6 | 移行後の再配置予定 | マルチプロトコルが要るか（EC2 → ECS / EKS / Fargate） |

**容量単価は 2 番目以降の話です。** 1 の面の数で先に方向が決まることが多く、
**面が多い構成では階層化を前提にしなくても FSx for ONTAP 側に寄ります。**

## 再現手順

```bash
# ゴールデンイメージから 30 面（階層化なし、差分 10%）
python3 scripts/cost_comparison.py --data-size 500 --clone-count 30 \
  --clone-delta-ratio 0.10 --tiering-policy snapshot-only
```

## 未確認のこと

- **面あたりの書き換え割合（差分）は測るべき値です。** 既定の 10% は NetApp の公表例から
  逆算した値で、こちらの実測ではありません
- **`lun clone` / file clone が FSx for ONTAP で単体で使えるかは確認していません**
- **このプロジェクトでは FlexClone の作成時間を実測していません。** 2 分未満という値は
  AWS が公開している他社事例のもので、こちらの構成の実測ではありません
- クローン数を増やしたときの性能影響は未測定です。QoS を設定しない場合の本番への影響も同じです

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [費用の比較](tco-comparison.md) | 容量単価と可用性を揃えた比較 |
| [移行方式の比較](migration-method-comparison.md) | どのツールで移行するか |
| [クイックスタート](quickstart.md) | 環境の構築と撤去 |

参考資料: [NetApp: FSx for ONTAP のクローニングでコストを削減し効率を高める](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)（この文書の技術的な記述は AWS の公式ドキュメントを出典にしています）
