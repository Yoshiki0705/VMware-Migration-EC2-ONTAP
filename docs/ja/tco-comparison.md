# ストレージ費用の比較 — EBS のみ構成と EBS + FSx for ONTAP 構成

移行後のデータ領域を Amazon EBS に置くか Amazon FSx for NetApp ONTAP に置くかで、月額が
どう変わるかを定価で並べます。

> **これはサンプル構成の定価計算であって、本番の見積りではありません。**
> 単価は AWS Price List API から 2026-09-13 に取得して固定した値です（ap-northeast-1）。
> 割引、既存のコミットメント、Savings Plans、EDP を含みません。
> **判断の前に AWS Pricing Calculator で確認してください。**

## 先に結論

**容量が小さいと EBS が安く、大きいと FSx for ONTAP が安くなります。** 分かれ目は
スループット容量でほぼ決まり、Multi-AZ・512 MB/s では**論理 14.0 TiB**、
Single-AZ・512 MB/s では**論理 6.5 TiB**でした。

| シナリオ（論理容量 / 5,000 IOPS / 512 MB/s） | EBS のみ | EBS + FSx for ONTAP | 差 |
|---|---|---|---|
| 1,024 GB、階層化なし（Multi-AZ） | $133.68 | $1,164.29 | +771% |
| 20,480 GB、hot 20%（Multi-AZ） | $2,001.46 | **$1,657.52** | **−17.2%** |
| 20,480 GB、hot 20%（Single-AZ） | $2,001.46 | **$908.21** | **−54.6%** |
| 51,200 GB、hot 20%（Multi-AZ） | $4,950.58 | **$2,976.14** | **−39.9%** |

月額 USD、OS ディスク（EBS gp3 50 GB）を両側に含みます。

**小さい構成で高いのは、最小 SSD 1,024 GiB とスループット容量が固定費として乗るためです。**
容量が増えると効率化と階層化で 1 論理 GB あたりの単価が下がり、どこかで逆転します。

## 論理 1 GB あたりの実効単価

**FSx for ONTAP が確保するのは論理容量ではなく、効率化後の物理データが収まる SSD です。**
ボリュームは既定でシンプロビジョニングで、cold なデータは容量プールへ階層化されます。
論理容量を 1:1 で EBS と並べると、FSx 側にしか無い削減をゼロとして扱うことになります。

100 TB 論理で計算した容量部分の単価（床の影響を除くため大きい容量で計算）:

| SSD に置く割合（hot） | 論理 1 GB あたり | EBS gp3 との比 |
|---|---|---|
| 100%（階層化しない） | $0.1125 | FSx が 1.17 倍高い |
| 50% | $0.0690 | FSx が 1.39 倍安い |
| 20% | $0.0429 | **FSx が 2.24 倍安い** |
| 10% | $0.0342 | FSx が 2.80 倍安い |

前提: 効率化後に残る率 0.30（VM ワークロードで 70% 削減）、階層化先のメタデータを
容量プール 10 GiB につき SSD 1 GiB、SSD 使用率を推奨上限の 80% で割る。

**階層化しないと 1 論理 GB あたりでも EBS を上回ります。** 効いているのは効率化と階層化の
組み合わせで、片方だけでは逆転しません。

## 逆転する論理容量

| スループット容量 | Multi-AZ | Single-AZ |
|---|---|---|
| 128 MB/s | 5.8 TiB | 2.9 TiB |
| 256 MB/s | 7.9 TiB | 4.1 TiB |
| 512 MB/s | 13.9 TiB | 6.5 TiB |
| 1,024 MB/s | 27.7 TiB | 11.6 TiB |
| 2,048 MB/s | 55.2 TiB | 23.1 TiB |
| 4,096 MB/s | 110.4 TiB | 46.1 TiB |

hot 20%、効率化後 0.30、IOPS は 3 IOPS/GB の範囲内。

**逆転点はスループット容量に比例します。** 固定費がそこに集中しているためで、
**必要以上のスループット容量を確保すると、逆転する容量がそのぶん遠のきます。**

> **必要なスループット容量を帯域の割り算では決められません。** 姉妹プロジェクトの実測では、
> 同じ手順・同じテンプレート・同じ交渉結果の 3 環境が 2.64 倍に散っています
> （[実測](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/1bedd45/docs/ja/verification/perf-matrix-results.md#f-3-と再現性の実測)）。
> **本シリーズでの実測は未了です。**

## 効率化と階層化が請求に効く経路

**効くのは「確保量を減らせるから」で、確保済みの容量が自動的に安くなるからではありません。**

| 機能 | 請求への効き方 | 出典 |
|---|---|---|
| 圧縮・重複排除・コンパクション | 物理データが縮み、確保すべき SSD が減る。**VM は 70% 削減が代表値** | [Managing storage capacity](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html) |
| シンプロビジョニング | ボリュームは既定でシン。**確保するのはファイルシステムの SSD で、ボリュームサイズの合計ではない** | [How to size](https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/) |
| 階層化（FabricPool） | cold を $0.0476/GB へ移す。SSD の $0.300/GB に対して 6.3 分の 1 | [同上](https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/) |
| Snapshot | 追加料金では課金されず、確保済み SSD を消費。**削減効果は階層化とブロック共有から出る** | [同上](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html) |
| FlexClone | 作成時にコピーせず、書き換えた分だけ増える | [Cloning](https://aws.amazon.com/blogs/storage/accelerate-development-refresh-cycles-and-optimize-cost-with-amazon-fsx-for-netapp-ontap-cloning) |

AWS が公表しているワークロード別の削減率（圧縮 + 重複排除）:

| ワークロード | 圧縮のみ | 重複排除のみ | 両方 |
|---|---|---|---|
| **仮想サーバー・仮想デスクトップ** | 55% | 70% | **70%** |
| 汎用ファイル共有 | 50% | 30% | 65% |
| データベース | 65〜70% | 0% | 65〜70% |
| エンジニアリングデータ | 55% | 30% | 75% |

**これは AWS の公表代表値で、このプロジェクトの実測値ではありません。** 実際の削減率は
データの内容で変わります。

## 複製を持つ場合の差

**FlexClone は作成時にデータをコピーしません。** EBS 側は Snapshot から復元した独立した
ボリュームになるため、複製ごとに全容量を確保します。

本番 2,048 GB、複製ごとの差分 10%、512 MB/s、階層化なしの場合:

| 複製の本数 | EBS の課金対象 | EBS 月額 | FSx の課金対象 | FSx 月額 |
|---|---|---|---|---|
| 0 本 | 2,048 GB | $215.18 | 2,048 GB | $1,080.83 |
| 3 本 | 8,192 GB | $860.72 | 2,662 GB | $1,080.83 |
| **5 本** | 12,288 GB | $1,291.08 | 3,072 GB | **$1,119.23** |
| 10 本 | 22,528 GB | $2,366.98 | 4,096 GB | $1,234.43 |

**この前提では 5 本で逆転します。** 差分の割合は測るべき値で、**10% という既定に根拠は
ありません。** 開発用の複製をどれだけ書き換えるかはワークロード依存です。

## 測らないと決まらない 3 つの値

**この比較の結論は、次の 3 つでほぼ決まります。どれも既定値には根拠がありません。**

| 値 | 影響 | 決め方 |
|---|---|---|
| hot / cold の比率 | 1 論理 GB あたりの単価。100% と 20% で 2.6 倍動く | AWS はアクセスログと最終アクセス時刻の分析、アプリケーション所有者への確認、パイロット運用での観測を挙げている |
| 効率化後に残る率 | 確保すべき SSD が直接変わる | 実データで測る。公表値は代表値 |
| スループット容量 | 逆転点に比例。固定費の大半 | 実測。**割り算では決まらない** |

## 制約と、費用に効く非対称

### 第一世代における SSD 減設の不可

**`MULTI_AZ_1` と `SINGLE_AZ_1` は SSD 容量を後から減らせません。** 減設は第二世代のみで、
最小 9% 刻み、減設後も 80% 以下という条件が付きます
（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/storage-capacity-and-IOPS.html)）。

**つまり、効率化を請求に反映させるには最初から少なく確保する必要があります。** 多めに確保して
後から削る運用は第一世代では成立しません。容量とスループットの変更後には 6 時間の
クールダウンもあります。

### 可用性の前提の不一致

**上の表は Multi-AZ の FSx for ONTAP と単一 AZ の EBS を並べています。** Multi-AZ は
2 つの AZ にファイルサーバーを持ち、障害時に自動フェイルオーバーします
（[出典](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html)）。
EBS 側に同等の可用性を持たせるには追加の仕組みが要り、その費用は含めていません。
**Single-AZ の行は可用性の前提が EBS 側に近づく代わりに、AZ 障害でファイルシステムが
使えなくなります。**

### 階層化はレイテンシと引き換え

容量プールのレイテンシは数十ミリ秒で、SSD のサブミリ秒とは別物です。
**hot 比率を下げると単価は下がりますが、cold に落ちたデータの読みは遅くなり、
リクエスト課金も乗ります**（読み $0.00037/1,000、書き $0.0047/1,000。**書きが 12.7 倍**）。

### ブート領域は EBS のまま

**FSx for ONTAP から EC2 をブートできません。** どちらの構成でも OS ディスクは EBS で、
比較の差分には出ませんが総額には残ります。

### EBS 側の無料ベースラインと上限

**EBS はボリューム 1 本ごとに 3,000 IOPS と 125 MB/s が無料で付きます。** 同じ総量を多くの
ボリュームに分けると無料分が台数だけ増えるため、EBS 側の請求は下がります。一方で
ボリューム 1 本には上限があります。

| 制約 | 値 | 出典 |
|---|---|---|
| gp3 の IOPS | 3,000〜80,000 | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |
| gp3 のスループット | 125〜2,000 MiB/s | [General Purpose SSD](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html) |
| gp3 のスループット対 IOPS | **確保 IOPS 1 につき 0.25 MiB/s まで**（2,000 MiB/s には 8,000 IOPS 必要） | 同上 |
| io2 の IOPS | 100〜256,000（**256,000 は Nitro 世代のみ。それ以外は 32,000**） | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |

`scripts/cost_comparison.py` はこの上限に反する構成を検出し、**金額を出しつつ実現不能で
あることを明示します。**

## この比較に含めていないもの

- **EC2 インスタンス費用**: 両構成で同じ台数・同じタイプを前提にしているため差分に出ません
- **バックアップ**: FSx for ONTAP のバックアップは消費量課金。**ボリューム削除時の最終
  バックアップは既定で取られ、残ると課金が続きます**（[撤去手順](quickstart.md#スタック削除)）
- **EBS Snapshot の保存料金**: S3 に保存され、容量に応じて課金されます
- **データ転送**: AZ 間・リージョン間。Multi-AZ のノード間レプリケーションはスループット
  容量の料金に含まれます
- **移行ツール**: AWS Transform / Shift Toolkit の費用、および移行中に両側の容量を同時に
  持つ期間
- **ライセンス**: OS・アプリケーションのライセンス移行条件

## 再現手順

```bash
# 既定（Multi-AZ、VM ワークロード 70% 削減、階層化なし）
python3 scripts/cost_comparison.py --data-size 20480

# 階層化して hot 20%、Single-AZ
python3 scripts/cost_comparison.py --data-size 20480 --hot-ratio 0.2 --deployment SINGLE_AZ_1

# 複製を 5 本持つ場合
python3 scripts/cost_comparison.py --data-size 2048 --clone-count 5 --clone-delta-ratio 0.10

# ワークロード別の削減率を切り替える
python3 scripts/cost_comparison.py --workload database --data-size 20480

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
