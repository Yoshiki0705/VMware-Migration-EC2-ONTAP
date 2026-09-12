# アーキテクチャ図

このページは本プロジェクトの構成図とフローを 1 か所に集めたものです。

**最終更新**: 2026-09-12

---

## 2 系統の図と使い分け

図は 2 系統あり、描き方が違います。

| 系統 | 対象 | 描き方 | 置き場 |
|------|------|--------|--------|
| 構成図・段の図 | AWS サービスが登場するもの | draw.io + AWS 公式アーキテクチャアイコン（`tools/build_diagrams.py` が生成） | `docs/_assets/diagrams/*.drawio` → `docs/_assets/images/*.svg` |
| 判断の分岐 | 方式選定 | Mermaid（このページに直接） | このファイル |

**AWS サービスが出てくる図は、検証済みかどうかに関わらず公式アイコンと公式サービス名で描きます。** 読者がサービスを取り違える方が、未検証の段が構成図に見えることより害が大きいためです。検証範囲は図の中の枠のタイトルと本文で示します。

Mermaid で書くのは方式選定だけです。選ぶ対象がツールであって AWS サービスではないので、サービスアイコンが意味を持ちません。

構成図の生成・検査手順は [図の作り方](../agent/diagrams.md) にあります。英語版は同じディレクトリの `-en` 付きファイルです。

---

## 移行元から AWS までの全体構成

![オンプレミスの Shift Toolkit / VMware ESXi と vCenter Server / 移行元 VM / ONTAP（NFS データストア）が縦に並び、ONTAP から SnapMirror で AWS 側の Amazon FSx for NetApp ONTAP 上の宛先ボリュームへ VMDK が複製される。その宛先ボリュームから、break 後に VMDK から変換された同じボリューム上の iSCSI LUN が生まれ、Amazon EC2 に iSCSI マルチパスで提供される。ブートディスクは Amazon Elastic Block Store から AMI として提供される。](../_assets/images/atx-fsxn-onprem-to-aws.svg)

図 1: NetApp Shift Toolkit を使う場合の移行元と移行先。Amazon FSx for NetApp ONTAP（以降 FSx for ONTAP）側に状態が 2 つあることを分けて描いています。

**SnapMirror が運ぶのは VMDK で、LUN ではありません。** 複製先は NFS データストアの中身（VMDK ファイル）をそのまま持つボリュームです。iSCSI LUN になるのはその後で、[Shift Toolkit 移行手順書](../ja/shift-toolkit-ec2-procedure.md) の Phase 4 では break がステップ 5、VMDK → LUN 変換がステップ 9 です。つまり変換は FSx for ONTAP 側で break の後に起きます。

**この経路で FSx for ONTAP が NFS を提供する場面はありません。** NFS はソース側のデータストアだけで、AWS 側のデータアクセスは iSCSI のみです（同手順書の必要ポート表に 2049 はなく、3260 があります）。したがって「NFS 用と iSCSI 用を別に描く」ではなく「1 本のボリュームの前後の状態を分けて描く」形にしています。

**変換は FlexClone ベースでサイズにほぼ依存しません。** ただしこの値は NetApp の記述と手順書の見積り表によるもので、本プロジェクトの実測ではありません。実測したのはブートディスク側の 10 ステップ（50 GB で約 1 時間 49 分。うち S3 アップロード 68 分、AMI インポート 36 分）で、データディスクの LUN 変換は測定範囲外です。内訳は [移行方式比較](../ja/migration-method-comparison.md#4-ダウンタイム比較実測--推定) にあります。

**VM Import/Export の経路は図に描いていません。** ブートディスクは VMDK → RAW → Amazon S3 → AMI という別経路をたどりますが、中間の S3 と AMI を描くと図が 2 倍になります。手順は [VM Import/Export 手順書](../ja/vm-import-procedure.md) にあります。

---

## iSCSI マルチパスの経路

![Amazon EC2 から 2 本のパスが伸び、Multi-AZ の Amazon FSx for NetApp ONTAP にある 2 つの iSCSI LIF（優先 AZ と待機 AZ）にそれぞれ入り、両方が同じ LUN に到達する。](../_assets/images/atx-fsxn-iscsi-multipath.svg)

図 2: 1 つの LUN に 2 本のパス。**フェイルオーバーを実行するのはホスト側の multipath です。** ストレージ側の役割は複数のパスを見せるところまでで、どちらを使うかはイニシエーターが決めます。

パス優先度の値（優先側 50 / 待機側 10）と、パス本数を帯域から決める算術は [FSx for ONTAP iSCSI 設定ガイド](../ja/fsxn-iscsi-setup.md) にあります。図に入れていないのは、**画像が縮小されたときに最初に読めなくなるのが図中で最も文字数の多い部分**だからです。

---

## AWS Transform を使う場合の構成

AWS Transform 経由の移行は、データが流れる経路と、それを制御する経路が別物です。1 枚に描くと線が交差して両方読めなくなるため 2 枚に分けています。

![移行元の Amazon EC2、ステージング、カットオーバー後の 3 行と、ブート / ルート領域とデータ領域の 2 列からなる表形式の図。ブートは Amazon Elastic Block Store、データは Amazon FSx for NetApp ONTAP に割り当たる。](../_assets/images/atx-fsxn-data-path.svg)

図 3: データ経路。**行がインスタンス、列が領域**として読みます。どのインスタンスのどの領域が Amazon Elastic Block Store と FSx for ONTAP のどちらに載るかを示します。

![AWS Transform が利用者の Amazon VPC の中の Amazon EC2 と AWS PrivateLink 経由で通信し、AWS Secrets Manager から FSx for ONTAP の資格情報を取得する制御経路。](../_assets/images/atx-fsxn-control-path.svg)

図 4: 制御経路。AWS Transform / AWS MGN と利用者側リソースの間の呼び出し関係です。

![Finalize 時に FSx for ONTAP のボリュームから FlexClone を作り、それをカットオーバー先の Amazon EC2 に iSCSI LUN として提供する流れ。](../_assets/images/atx-fsxn-finalize-flexclone.svg)

図 5: Finalize での FlexClone。ステージングボリュームから複製を作って移行先に渡す段階です。

手順は [AWS Transform 移行手順書](../ja/aws-transform-migration-procedure.md)、コンソール操作は [コンソール手順](../ja/atx-fsxn-console-procedure.md) にあります。

---

## 移行ジャーニーの段

> **この節は検証結果ではありません。** Phase 1（リホスト）だけが本プロジェクトの検証範囲で、Phase 2 / Phase 3 と選択肢は整理です。図の中の枠のタイトルにも同じことを書いています。

![現在地の VMware ESXi から、リホスト以外の選択肢（Amazon Elastic VMware Service / NC2 + ONTAP / Red Hat OpenShift Service on AWS）と、Phase 1 リホスト（Amazon EC2 と Amazon FSx for NetApp ONTAP の iSCSI LUN / NFS / SMB）、Phase 2 リプラットフォーム（上の行に Amazon Elastic Container Service / Amazon Elastic Kubernetes Service / AWS Batch / AWS Parallel Computing Service / AWS Deadline Cloud、下の行に Amazon CloudFront / AWS Transfer Family / S3 Access Points / FSx for ONTAP の NFS / SMB / iSCSI）、Phase 3 リファクタ（上の行に AWS Fargate / AWS Lambda、下の行に Amazon Simple Storage Service / Amazon DynamoDB / S3 Access Points / FSx for ONTAP）へ段が進む図。](../_assets/images/atx-fsxn-migration-journey.svg)

図 6: リホストから先の段と、リホスト以外の選択肢。各段は上の行がコンピュート、下の行がデータの入口とストレージです。

**同じファイルシステムが段をまたいで使えることが、この図の要点です。** Phase 1 で FSx for ONTAP に置いたボリュームは、Phase 2 でコンテナ・バッチ・レンダリングのワークロードから NFS / SMB / iSCSI のどれでも参照でき、同じデータを S3 Access Points 経由でオブジェクト API から、AWS Transfer Family 経由で SFTP から、Amazon CloudFront 経由で配信からも扱えます。Phase 3 でも同じ入口が使えます。移行のたびにデータを動かし直す必要がありません。

**本検証で測ったのは Phase 1 の iSCSI だけです。** NFS と SMB は同じファイルシステムが同時に提供できるプロトコルですが、本プロジェクトでは iSCSI マルチパスのみを実測しています。Phase 2 / Phase 3 のサービスとの組み合わせも未検証で、どの組み合わせが実際に成立するかは各サービス側の対応状況を確認してください。

**段の中に線を引いているのは Phase 1 だけです。** Phase 2 の Amazon Elastic Container Service と Amazon Elastic Kubernetes Service は互いに代替であって流れではないので、矢印を引くと「ECS の次が EKS」と読めてしまいます。枠と並びが「この段の構成要素」を表しています。Phase 1 の Amazon EC2 → FSx for ONTAP だけは実測した経路なので引いています。

NC2（Nutanix）だけ箱で描いてあるのはサードパーティの製品だからです。公式アイコンは AWS のサービスにだけ使います。S3 Access Points はサービスではなくファイルシステムの前に置く入口なので、サービスアイコンではなくリソースアイコン（48px）を使い、両方の段で FSx for ONTAP の手前に並べています。

---

## 移行の選択肢とデータ層の可搬性

この 2 枚は検証結果ではなく整理です。**それでも AWS のサービスは公式アイコンと公式サービス名で描いています。** 読者がサービスを取り違える方が、整理の図が構成図に見えることより害が大きいためです。

![AWS が公式に示す VMware ワークロードの 5 つのパスウェイを 5 段に並べた図。1 段目は Amazon EC2 への移行、2 段目は AWS 上でのモダナイゼーション、3 段目は AWS 上での VMware 継続、4 段目はオンプレミスでの AWS 実行、5 段目は AWS 上でのサードパーティハイパーバイザー。](../_assets/images/atx-fsxn-vmware-pathways.svg)

図 7: AWS が公式に示す 5 つのパスウェイ。**どの段でも Amazon FSx for NetApp ONTAP をデータ層に置けることを位置で示しています。** 段の間に線を引いていないのは、5 つが順序ではなく選択肢だからです。

移行ツール（AWS Transform / AWS Application Migration Service / Cirrus Migrate Cloud / Shift Toolkit）は図に入れていません。4 つ足すと 1 段が 2 行になり、図の主題がツールの一覧に移ります。ツールの選び方は [移行方式比較](../ja/migration-method-comparison.md) にあります。

![左がオンプレミス、右が AWS。オンプレミス側はハイパーバイザーがデータストアとして NetApp ONTAP（FAS / AFF）を使い、AWS 側は Amazon EC2 が Amazon FSx for NetApp ONTAP を使う。両者は SnapMirror で双方向につながる。](../_assets/images/atx-fsxn-ontap-portability.svg)

図 8: 上がコンピュート、下がデータ層。**コンピュートを変えてもデータ層は同じで、境界をまたぐのは SnapMirror だけです。** オンプレミス側の枠は AWS 公式の Corporate data center バッジで、紫の破線（VPC の色）は使っていません。

---

## マルチプロトコルと FlexClone の仕組み

![左に VMware ESXi、Microsoft Hyper-V、Amazon EC2 が縦に並び、右の 1 つの ONTAP ボリュームの中にある VMDK、VHDX、iSCSI LUN へそれぞれ NFS、SMB、iSCSI で到達する。](../_assets/images/atx-fsxn-multiprotocol-volume.svg)

図 9: 1 つのボリュームの中に 3 つの表現があり、3 つのプロトコルで同時に読めます。**箱を 3 つに分けたのは、収束先を 1 つにすると入口が足りないから**です（直交ルーティングが 1 ノードに与える入口は左と上の 2 レーンだけ）。この図に AWS Cloud の枠が無いのは、Amazon EC2 と VMware ESXi / Hyper-V が同じ列に並ぶため、枠を 1 つ置くと Amazon EC2 が枠の外に出てしまうからです。

![Amazon FSx for NetApp ONTAP の同一ボリューム内で、オリジナル（VMDK）から FlexClone（変換後 / iSCSI LUN）がメタデータのみで作られ、両方が同じ共有された物理ブロックを指す。](../_assets/images/atx-fsxn-flexclone-blocks.svg)

図 10: クローンとオリジナルは同じ物理ブロックを共有します。図 5（Finalize でのライフサイクル）とは別の図で、**あちらは時間の経過、こちらは静的な構造**です。クローン直後の追加物理消費 35.5 MiB（論理 7.91 GiB に対して）は AWS Transform の検証で測った値です。

ONTAP の Snapshot / FlexClone / LUN に AWS パッケージのアイコンは無いので箱で描いています。Amazon EBS の Snapshot アイコンを借りると、ONTAP の機構を Amazon EBS のものとして示すことになります。

---

## 方式選定の分岐

分岐の根拠、各方式の制約、実測ダウンタイムは [移行方式比較](../ja/migration-method-comparison.md) にあります。**そちらが判断の基準で、この図はその要約です。**

```mermaid
flowchart TD
    Start["VMware から Amazon EC2 への移行を検討"]
    Q1{"移行元 VM は<br/>ONTAP NFS<br/>データストア上か"}
    Q2{"停止時間の要件は"}
    Q3{"既存の Veeam 環境が<br/>あるか"}
    Q4{"規模と自動化の要件は"}

    ATX_ONTAP["AWS Transform"]
    Shift["NetApp Shift Toolkit"]
    Veeam["Veeam Restore to EC2"]
    ATX_ANY["AWS Transform"]
    VMImport["VM Import/Export"]

    Start --> Q1
    Q1 -->|Yes| Q2
    Q2 -->|"分レベルが必須"| ATX_ONTAP
    Q2 -->|"30 分〜2 時間を許容"| Shift
    Q1 -->|No| Q3
    Q3 -->|Yes| Veeam
    Q3 -->|No| Q4
    Q4 -->|"大規模 / 自動化必須"| ATX_ANY
    Q4 -->|"小規模 / 単発"| VMImport

    style Shift fill:#0067C5,color:#fff,stroke:#00447f
    style ATX_ONTAP fill:#FF9900,color:#000,stroke:#8a5200
    style ATX_ANY fill:#FF9900,color:#000,stroke:#8a5200
```

図 11: 4 方式の分岐。AWS Transform は移行元を問わないため 2 か所に現れます。**葉には方式名しか入れていません。** 成熟度（AWS Transform の FSx for ONTAP 宛先は 2026 年 8 月 30 日に GA、Shift Toolkit の EC2 対応は Early Preview）と各方式の制約は比較表にあり、図に入れると横幅が 2 倍になって縮小時に読めなくなります。

どの方式も排他ではなく、VM 特性ごとに使い分ける前提です（[組み合わせパターン](../ja/migration-method-comparison.md#6-組み合わせパターン)）。

---

## 関連ドキュメント

- [移行方式比較](../ja/migration-method-comparison.md)
- [Shift Toolkit EC2 移行手順書](../ja/shift-toolkit-ec2-procedure.md)
- [AWS Transform 移行手順書](../ja/aws-transform-migration-procedure.md)
- [FSx for ONTAP iSCSI 設定ガイド](../ja/fsxn-iscsi-setup.md)
- [図の作り方](../agent/diagrams.md)
