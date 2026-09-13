# ストレージ費用の比較 — EBS のみ構成と EBS + FSx for ONTAP 構成

移行後のデータ領域を Amazon EBS に置くか Amazon FSx for NetApp ONTAP に置くかで、月額が
どう変わるかを定価で並べます。

> **これはサンプル構成の定価計算であって、本番の見積りではありません。**
> 単価は AWS Price List API から 2026-09-13 に取得して固定した値です（ap-northeast-1）。
> 割引、既存のコミットメント、Savings Plans、EDP を含みません。
> **判断の前に AWS Pricing Calculator で確認してください。**

## 先に結論

**ストレージの定価だけを見ると、FSx for ONTAP 構成は EBS のみ構成より高くなります。** 検証した
どのシナリオでも逆転せず、VM 台数を 200 まで増やしても逆転する台数は見つかりませんでした。

**そのうえで、定価の差だけでは決まりません。** FlexClone、SnapMirror、マルチプロトコルは
EBS 構成には無く、EBS のボリューム 1 本では出せない性能要件もあります。この文書は差額を
提示するところまでで、**どちらを選ぶかは差額と機能を並べて決める必要があります。**

| シナリオ | EBS のみ | EBS + FSx for ONTAP | 差 |
|---|---|---|---|
| 単一 VM、1,024 GB、512 MB/s、5,000 IOPS（Multi-AZ） | $133.68 | $1,164.29 | +$1,030.61 |
| 同・Single-AZ | $133.68 | $661.60 | +$527.92 |
| 20 VM、各 100 GB、総 512 MB/s、総 5,000 IOPS（Multi-AZ） | $288.00 | $1,469.63 | +$1,181.63 |

すべて月額 USD、OS ディスク（EBS gp3 50 GB）を両側に含みます。

## スループット容量の支配

**FSx for ONTAP の請求で最も大きいのは容量ではなくスループット容量です。** 1,024 GB を
固定してスループット容量だけ変えると、合計に占める割合はこう動きます。

| スループット容量 | 月額合計 | うちスループット | 割合 |
|---|---|---|---|
| 128 MB/s | $579.27 | $193.41 | 33.4% |
| 512 MB/s | $1,159.49 | $773.63 | 66.7% |
| 2,048 MB/s | $3,480.39 | $3,094.53 | 88.9% |
| 4,096 MB/s | $6,574.92 | $6,189.06 | 94.1% |

**確保した量で課金されるので、使っていなくても請求されます。** 見積りを詰める順序は、
容量ではなくスループット容量からです。

> **必要なスループット容量を帯域の割り算で決められません。** 姉妹プロジェクトの実測では、
> 同じ手順・同じテンプレート・同じ交渉結果の 3 環境が 2.64 倍に散っています
> （[実測](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/1bedd45/docs/ja/verification/perf-matrix-results.md#f-3-と再現性の実測)）。
> **本シリーズでの実測は未了です。**

## Multi-AZ と Single-AZ の差

**「Single-AZ は半額」は容量と IOPS にしか当てはまりません。**

| 項目 | Multi-AZ | Single-AZ | 比 |
|---|---|---|---|
| SSD ストレージ | $0.300/GB-Mo | $0.150/GB-Mo | 50.0% |
| 容量プール | $0.0476/GB-Mo | $0.0238/GB-Mo | 50.0% |
| 超過 SSD IOPS | $0.0408/IOPS-Mo | $0.0204/IOPS-Mo | 50.0% |
| **スループット容量** | **$1.511/MBps-Mo** | **$0.906/MBps-Mo** | **60.0%** |
| 容量プールのリクエスト | 同額 | 同額 | 100% |

スループット容量が合計の大半を占めるため、**Single-AZ にしても合計は半分になりません。**
上の単一 VM のシナリオでは $1,164.29 → $661.60（56.8%）でした。

Single-AZ を選ぶと AZ 障害でファイルシステムが使えなくなります。**費用だけで選ぶ対象では
ありません。**

## 効率化が請求に効かない理由

**重複排除と圧縮はデータを縮めますが、既定では請求を下げません。** SSD は確保した量で
課金されるため、**確保容量を実際に下げるまで請求は変わりません。** 空いた分は
「請求対象のヘッドルーム」として残ります。

同じことが ONTAP Snapshot にも当てはまります。**Snapshot は追加料金では課金されませんが、
確保済みの SSD を消費します。** すでに払っている容量を使うので、無料ではなく前払いです。

区分の詳細は
[FSx for ONTAP Adoption Playbook の provisioned versus consumed](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/cost/notes/provisioned-versus-consumed.md)
にあります。

## 容量プールのリクエスト課金

階層化すると、容量プールにはストレージ料金とは別にリクエスト課金が乗ります。
**読みと書きで単価が 12.7 倍違います。**

| 種別 | 単価 | 100 万リクエストあたり |
|---|---|---|
| 読み | $0.00037 / 1,000 | $0.37 |
| 書き | $0.0047 / 1,000 | $4.70 |

**「アクセスが少ないデータを容量プールに落とせば安くなる」はアクセス頻度次第で逆転します。**
落とした先を読み続けるなら、ストレージ単価の差をリクエスト課金が食います。

## EBS 側の無料ベースラインと上限

**EBS はボリューム 1 本ごとに 3,000 IOPS と 125 MB/s が無料で付きます。** 同じ総量を多くの
ボリュームに分けると、無料分が台数だけ増えるため EBS 側の請求は下がります。FSx for ONTAP は
スループット容量をファイルシステムに 1 回買うので、この形の恩恵を受けません。

一方で、**ボリューム 1 本には上限があります。**

| 制約 | 値 | 出典 |
|---|---|---|
| gp3 の IOPS | 3,000〜80,000 | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |
| gp3 のスループット | 125〜2,000 MiB/s | [General Purpose SSD](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html) |
| gp3 のスループット対 IOPS | **確保 IOPS 1 につき 0.25 MiB/s まで**（2,000 MiB/s には 8,000 IOPS 必要） | 同上 |
| io2 の IOPS | 100〜256,000（**256,000 は Nitro 世代のみ。それ以外は 32,000**） | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |

`scripts/cost_comparison.py` はこの上限に反する構成を検出し、**金額を出しつつ実現不能で
あることを明示します。** 上限を超えた構成に金額だけを並べると、EBS 側に出せない安い値が
並ぶためです。

## この比較に含めていないもの

**含めていないものが請求の一部を占めます。** 以下は両構成で差が出るか、条件次第で無視できません。

- **EC2 インスタンス費用**: 両構成で同じ台数・同じタイプを前提にしているため差分に出ません。
  総額には含まれます
- **バックアップ**: FSx for ONTAP のバックアップは消費量課金です。**ボリューム削除時の
  最終バックアップは既定で取られ、残ると課金が続きます**（[撤去手順](quickstart.md#スタック削除)）
- **EBS Snapshot の保存料金**: S3 に保存され、容量に応じて課金されます
- **データ転送**: AZ 間・リージョン間の転送。Multi-AZ のノード間レプリケーションは
  スループット容量の料金に含まれます
- **移行ツール**: AWS Transform / Shift Toolkit の費用、および移行中に両側の容量を
  同時に持つ期間
- **ライセンス**: OS・アプリケーションのライセンス移行条件

## 再現手順

```bash
# 既定（Multi-AZ、1,000 GB、512 MB/s、5,000 IOPS）
python3 scripts/cost_comparison.py

# 配置と条件を変える
python3 scripts/cost_comparison.py --deployment SINGLE_AZ_1 --data-size 1024 --iops 5000

# 階層化するなら読みと書きのリクエスト数を渡す
python3 scripts/cost_comparison.py --data-size 1024 \
  --pool-read-requests-millions 500 --pool-write-requests-millions 20

# 固定した単価を Price List API と突き合わせる（AWS 認証が必要）
python3 scripts/cost_comparison.py --check-prices
```

**単価は 19 件すべて SKU と usagetype を持っています。** `--check-prices` は API の
`pricePerUnit` と 1 件ずつ比較し、ずれた項目名と両方の値を出して終了コード 1 で落ちます。

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [移行方式の比較](migration-method-comparison.md) | どのツールで移行するか |
| [クイックスタート](quickstart.md) | 環境の構築と撤去 |
| [iSCSI セットアップ](fsxn-iscsi-setup.md) | LUN の作成とマウント |
