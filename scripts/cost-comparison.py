#!/usr/bin/env python3
"""
EBS vs FSx for ONTAP コスト比較スクリプト

目的: 移行後のストレージコストを EBS のみ構成と EBS + FSx for ONTAP ハイブリッド構成で比較する。
東京リージョン (ap-northeast-1) の料金で計算。

Usage:
    python3 cost-comparison.py --data-size 1000 --throughput 512 --iops 5000
    # 階層化する場合は容量プールのリクエスト数を必ず渡す（リクエスト課金があるため）
    python3 cost-comparison.py --data-size 1000 --throughput 512 --pool-requests-millions 500
    # 効率化で空いた分だけ確保容量を下げる操作をモデル化する
    python3 cost-comparison.py --data-size 1000 --efficiency 0.6 --shrink-provisioned

**これはサンプル構成の定価計算であって、本番の見積りではない。** 単価は 2026-06 時点の
公開情報で、割引と既存のコミットメントを含まない。判断の前に料金ページと
AWS Pricing Calculator で確認する。

課金の区分（確保した量 / 消費した量）は FSx for ONTAP Adoption Playbook の
docs/ja/domains/cost/notes/provisioned-versus-consumed.md に従う。**効率化は既定では
請求を下げない。** SSD は確保した量で課金されるため、確保容量を下げるまで請求は変わらない。

  https://aws.amazon.com/fsx/netapp-ontap/pricing/
  https://aws.amazon.com/ebs/pricing/
"""

import argparse
import json
from dataclasses import dataclass

# ==============================================================================
# 料金定義（ap-northeast-1, 2026年6月時点）
# 出典: https://aws.amazon.com/fsx/netapp-ontap/pricing/
#        https://aws.amazon.com/ebs/pricing/
# ==============================================================================


@dataclass
class FsxnPricing:
    """FSx for ONTAP 料金 (ap-northeast-1, Multi-AZ)

    **SSD 容量・SSD IOPS・スループット容量は「確保した量」で課金される。** 使っていなくても
    請求される。容量プールとバックアップは「消費した量」。この区分が見積もりのずれの大半を
    説明する。区分の出典は FSx for ONTAP Adoption Playbook の
    docs/ja/domains/cost/notes/provisioned-versus-consumed.md。
    """

    ssd_per_gb_month: float = 0.250  # SSD ストレージ $/GB/月（確保量）
    capacity_pool_per_gb_month: float = 0.020  # 容量プールストレージ $/GB/月（消費量）
    throughput_per_mbps_month: float = 0.500  # スループット容量 $/MBps/月（確保量）
    # **3 IOPS/GB までは含まれる。** 超過分だけが課金対象で、
    # 「IOPS を上げたら必ず課金が増える」は誤り。
    ssd_included_iops_per_gb: int = 3
    ssd_iops_per_month: float = 0.020  # 3 IOPS/GB 超過分 $/IOPS/月
    # **容量プールにはストレージ料金とは別にリクエスト課金がある。** 階層化した
    # データを読むたびに発生するので「落とせば安くなる」はアクセス頻度次第で逆転する。
    capacity_pool_per_million_requests: float = 0.0055  # $/100 万リクエスト
    # iSCSI アクセスそのものに追加料金は無い。Multi-AZ の AZ 間レプリケーション転送は
    # スループット容量の料金に含まれる（別課金ではない）。


@dataclass
class EbsPricing:
    """EBS 料金 (ap-northeast-1)"""

    gp3_per_gb_month: float = 0.096  # gp3 $/GB/月
    gp3_baseline_iops: int = 3000  # gp3 ベースライン IOPS（無料）
    gp3_baseline_throughput: int = 125  # gp3 ベースラインスループット MB/s（無料）
    gp3_iops_per_month: float = 0.006  # 追加 IOPS $/IOPS/月 (3000 超過分)
    gp3_throughput_per_mbps_month: float = 0.048  # 追加スループット $/MBps/月 (125 超過分)
    io2_per_gb_month: float = 0.142  # io2 $/GB/月
    io2_per_iops_month: float = 0.074  # io2 $/IOPS/月


# ==============================================================================
# 計算ロジック
# ==============================================================================


def calculate_fsxn_cost(
    data_size_gb: float,
    throughput_mbps: int,
    ssd_ratio: float = 1.0,
    efficiency_ratio: float = 1.0,
    iops: int = 0,
    pool_requests_millions: float = 0.0,
    shrink_provisioned: bool = False,
    pricing: FsxnPricing | None = None,
) -> dict:
    """FSx for ONTAP の月額コストを計算。

    **効率化は請求を下げない。** 重複排除と圧縮はデータを縮めるが SSD は確保した量で
    課金されるので、既定では `efficiency_ratio` を確保容量に反映させず「同じ確保容量に
    どれだけ論理データが入るか」としてだけ報告する。確保容量を実際に下げる操作を
    モデル化する場合に `shrink_provisioned=True` を渡す。

    Args:
        data_size_gb: 論理データサイズ (GB)
        throughput_mbps: 確保するスループット (MB/s)
        ssd_ratio: SSD に確保する割合。残りは容量プールに置く前提
        efficiency_ratio: 効率化後の物理データ率 (0.6 = 40% 削減)
        iops: 必要 IOPS。3 IOPS/GB を超えた分だけが課金対象
        pool_requests_millions: 容量プールへの月間リクエスト数（百万単位）
        shrink_provisioned: 効率化で空いた分だけ確保容量を下げる場合に True
        pricing: 料金オブジェクト
    """
    if pricing is None:
        pricing = FsxnPricing()

    provisioned_ssd_gb = data_size_gb * ssd_ratio
    if shrink_provisioned:
        provisioned_ssd_gb *= efficiency_ratio

    physical_size_gb = data_size_gb * efficiency_ratio
    capacity_pool_gb = max(0.0, physical_size_gb - provisioned_ssd_gb)

    ssd_cost = provisioned_ssd_gb * pricing.ssd_per_gb_month
    capacity_pool_cost = capacity_pool_gb * pricing.capacity_pool_per_gb_month
    request_cost = pool_requests_millions * pricing.capacity_pool_per_million_requests
    throughput_cost = throughput_mbps * pricing.throughput_per_mbps_month

    included_iops = int(provisioned_ssd_gb * pricing.ssd_included_iops_per_gb)
    extra_iops = max(0, iops - included_iops)
    iops_cost = extra_iops * pricing.ssd_iops_per_month

    total = ssd_cost + capacity_pool_cost + request_cost + throughput_cost + iops_cost
    headroom = provisioned_ssd_gb - min(physical_size_gb, provisioned_ssd_gb)

    return {
        "service": "FSx for ONTAP (Multi-AZ)",
        "logical_data_gb": data_size_gb,
        "physical_data_gb": round(physical_size_gb, 1),
        "provisioned_ssd_gb": round(provisioned_ssd_gb, 1),
        "efficiency_headroom_gb": round(headroom, 1),
        "efficiency_reduces_bill": shrink_provisioned,
        "capacity_pool_gb": round(capacity_pool_gb, 1),
        "throughput_mbps": throughput_mbps,
        "included_iops": included_iops,
        "billed_extra_iops": extra_iops,
        "pool_requests_millions": pool_requests_millions,
        "cost_ssd": round(ssd_cost, 2),
        "cost_capacity_pool": round(capacity_pool_cost, 2),
        "cost_pool_requests": round(request_cost, 2),
        "cost_throughput": round(throughput_cost, 2),
        "cost_extra_iops": round(iops_cost, 2),
        "total_monthly_usd": round(total, 2),
    }


def calculate_ebs_gp3_cost(
    data_size_gb: float,
    iops: int = 3000,
    throughput_mbps: int = 125,
    pricing: EbsPricing | None = None,
) -> dict:
    """
    EBS gp3 の月額コストを計算。

    Args:
        data_size_gb: データサイズ (GB)
        iops: 必要な IOPS
        throughput_mbps: 必要なスループット (MB/s)
        pricing: 料金オブジェクト
    """
    if pricing is None:
        pricing = EbsPricing()
    storage_cost = data_size_gb * pricing.gp3_per_gb_month

    # 追加 IOPS コスト（3000 超過分）
    extra_iops = max(0, iops - pricing.gp3_baseline_iops)
    iops_cost = extra_iops * pricing.gp3_iops_per_month

    # 追加スループットコスト（125 MB/s 超過分）
    extra_throughput = max(0, throughput_mbps - pricing.gp3_baseline_throughput)
    throughput_cost = extra_throughput * pricing.gp3_throughput_per_mbps_month

    total = storage_cost + iops_cost + throughput_cost

    return {
        "service": "EBS gp3",
        "data_gb": data_size_gb,
        "provisioned_iops": iops,
        "provisioned_throughput_mbps": throughput_mbps,
        "cost_storage": round(storage_cost, 2),
        "cost_extra_iops": round(iops_cost, 2),
        "cost_extra_throughput": round(throughput_cost, 2),
        "total_monthly_usd": round(total, 2),
    }


def calculate_ebs_io2_cost(
    data_size_gb: float,
    iops: int = 10000,
    pricing: EbsPricing | None = None,
) -> dict:
    """EBS io2 の月額コスト計算（高 IOPS 要件向け）。"""
    if pricing is None:
        pricing = EbsPricing()
    storage_cost = data_size_gb * pricing.io2_per_gb_month
    iops_cost = iops * pricing.io2_per_iops_month
    total = storage_cost + iops_cost

    return {
        "service": "EBS io2",
        "data_gb": data_size_gb,
        "provisioned_iops": iops,
        "cost_storage": round(storage_cost, 2),
        "cost_iops": round(iops_cost, 2),
        "total_monthly_usd": round(total, 2),
    }


# ==============================================================================
# レポート生成
# ==============================================================================


def generate_comparison_report(
    data_size_gb: float,
    throughput_mbps: int,
    efficiency_ratio: float,
    iops: int,
    pool_requests_millions: float = 0.0,
    shrink_provisioned: bool = False,
) -> str:
    """比較レポートを Markdown 形式で生成。"""
    fsxn = calculate_fsxn_cost(
        data_size_gb,
        throughput_mbps,
        efficiency_ratio=efficiency_ratio,
        iops=iops,
        pool_requests_millions=pool_requests_millions,
        shrink_provisioned=shrink_provisioned,
    )
    ebs_gp3 = calculate_ebs_gp3_cost(data_size_gb, iops=iops, throughput_mbps=throughput_mbps)
    ebs_io2 = calculate_ebs_io2_cost(data_size_gb, iops=iops)

    # OS ディスク（EBS gp3 50GB）は両方の構成で共通
    os_disk_cost = 50 * EbsPricing().gp3_per_gb_month

    lines = []
    lines.append("# ストレージコスト比較レポート")
    lines.append("")
    lines.append("**リージョン**: ap-northeast-1 (東京)")
    lines.append(f"**データサイズ**: {data_size_gb} GB (論理)")
    lines.append(f"**必要 IOPS**: {iops}")
    lines.append(f"**必要スループット**: {throughput_mbps} MB/s")
    lines.append(f"**効率化の想定削減率**: {round((1 - efficiency_ratio) * 100)}%")
    lines.append(f"**容量プールへの月間リクエスト**: {pool_requests_millions} 百万")
    lines.append("")
    lines.append("> ⚠️ **これはサンプル構成の定価計算であって、本番の見積りではありません。**")
    lines.append("> 単価は 2026-06 時点の公開情報です。**料金は改定されるため、判断の前に")
    lines.append("> [FSx for ONTAP 料金ページ](https://aws.amazon.com/fsx/netapp-ontap/pricing/)")
    lines.append("> と AWS Pricing Calculator で確認してください。** 割引や既存のコミットメントは")
    lines.append("> 含めていません。")
    lines.append("")
    lines.append("> **効率化は既定では請求を下げません。** 重複排除と圧縮はデータを縮めますが、")
    lines.append("> SSD は確保した量で課金されます。確保容量を実際に下げるまで請求は変わりません。")
    if shrink_provisioned:
        lines.append("> この計算では確保容量を下げる操作を行った前提にしています。")
    lines.append("")
    lines.append("## 構成比較")
    lines.append("")
    lines.append(
        "| 項目 | 構成 A: EBS gp3 のみ | 構成 B: EBS + FSx for ONTAP | 構成 C: EBS io2 (高IOPS) |"
    )
    lines.append("|------|---------------------|-------------------|------------------------|")
    lines.append("| OS ディスク | EBS gp3 50GB | EBS gp3 50GB | EBS gp3 50GB |")
    lines.append(
        f"| データディスク | EBS gp3 {data_size_gb}GB | FSx for ONTAP iSCSI {data_size_gb}GB | EBS io2 {data_size_gb}GB |"
    )
    lines.append(
        f"| IOPS | {iops}（確保） | 3 IOPS/GB 込み + 超過 {fsxn['billed_extra_iops']} | {iops}（確保） |"
    )
    lines.append(
        "| Snapshot | EBS Snapshot（非同期・S3 に保存） | ONTAP Snapshot（ボリューム内） | EBS Snapshot |"
    )
    lines.append(
        "| クローン | Snapshot から新ボリューム（容量を消費） | FlexClone（作成はメタデータのみ） |"
        " Snapshot から新ボリューム |"
    )
    lines.append(
        "| レプリケーション | Snapshot コピー / EBS レプリケーション | SnapMirror |"
        " Snapshot コピー |"
    )
    lines.append(
        f"| 重複排除・圧縮 | なし | あり（{round((1 - efficiency_ratio) * 100)}% 削減想定。"
        "**確保容量を下げないと請求は変わらない**） | なし |"
    )
    lines.append(
        "| 課金の性質 | 確保した量 | **SSD・IOPS・スループットは確保した量。容量プールは消費量 +"
        " リクエスト** | 確保した量 |"
    )
    lines.append("")
    lines.append("## 月額コスト詳細")
    lines.append("")
    lines.append("### 構成 A: EBS gp3 のみ")
    lines.append(f"- OS ディスク: ${os_disk_cost:.2f}")
    lines.append(f"- データストレージ: ${ebs_gp3['cost_storage']:.2f}")
    lines.append(f"- 追加 IOPS: ${ebs_gp3['cost_extra_iops']:.2f}")
    lines.append(f"- 追加スループット: ${ebs_gp3['cost_extra_throughput']:.2f}")
    lines.append(f"- **合計: ${os_disk_cost + ebs_gp3['total_monthly_usd']:.2f}/月**")
    lines.append("")
    lines.append("### 構成 B: EBS (OS) + FSx for ONTAP (Data)")
    lines.append(f"- OS ディスク (EBS gp3): ${os_disk_cost:.2f}")
    lines.append(
        f"- FSx for ONTAP 確保 SSD ({fsxn['provisioned_ssd_gb']} GB): ${fsxn['cost_ssd']:.2f}"
    )
    lines.append(
        f"- FSx for ONTAP 容量プール ({fsxn['capacity_pool_gb']} GB): ${fsxn['cost_capacity_pool']:.2f}"
    )
    lines.append(
        f"- FSx for ONTAP スループット ({throughput_mbps} MB/s): ${fsxn['cost_throughput']:.2f}"
    )
    lines.append(
        f"- FSx for ONTAP 超過 IOPS ({fsxn['billed_extra_iops']} IOPS、"
        f"{fsxn['included_iops']} は 3 IOPS/GB として込み): ${fsxn['cost_extra_iops']:.2f}"
    )
    lines.append(
        f"- 容量プールのリクエスト ({fsxn['pool_requests_millions']} 百万): "
        f"${fsxn['cost_pool_requests']:.2f}"
    )
    lines.append(f"- **合計: ${os_disk_cost + fsxn['total_monthly_usd']:.2f}/月**")
    lines.append(
        f"- 確保 SSD {fsxn['provisioned_ssd_gb']} GB に対し物理データは "
        f"{fsxn['physical_data_gb']} GB（空き {fsxn['efficiency_headroom_gb']} GB は"
        "**請求対象のまま**）"
    )
    lines.append("")
    lines.append("### 構成 C: EBS io2 (高 IOPS)")
    lines.append(f"- OS ディスク (EBS gp3): ${os_disk_cost:.2f}")
    lines.append(f"- データストレージ: ${ebs_io2['cost_storage']:.2f}")
    lines.append(f"- IOPS: ${ebs_io2['cost_iops']:.2f}")
    lines.append(f"- **合計: ${os_disk_cost + ebs_io2['total_monthly_usd']:.2f}/月**")
    lines.append("")
    lines.append("## コスト比較サマリー")
    lines.append("")
    total_a = os_disk_cost + ebs_gp3["total_monthly_usd"]
    total_b = os_disk_cost + fsxn["total_monthly_usd"]
    total_c = os_disk_cost + ebs_io2["total_monthly_usd"]
    lines.append("| 構成 | 月額 | 年額 | 対構成 A 比 |")
    lines.append("|------|------|------|-----------|")
    lines.append(f"| A: EBS gp3 のみ | ${total_a:.2f} | ${total_a * 12:.2f} | — |")
    lines.append(
        f"| B: EBS + FSx for ONTAP | ${total_b:.2f} | ${total_b * 12:.2f} | {((total_b / total_a) - 1) * 100:+.1f}% |"
    )
    lines.append(
        f"| C: EBS io2 | ${total_c:.2f} | ${total_c * 12:.2f} | {((total_c / total_a) - 1) * 100:+.1f}% |"
    )
    lines.append("")
    lines.append("## 何と引き換えに何を得るか")
    lines.append("")
    lines.append("**片側だけを並べると判断できません。** 選択ごとに、下がるものと受け入れる")
    lines.append("ものを対称に置きます。")
    lines.append("")
    lines.append("| 選択 | 得られるもの | 受け入れるもの |")
    lines.append("|---|---|---|")
    lines.append(
        "| EBS gp3 のみ | 課金要素が少なく見積りが単純。追加 IOPS / スループットは超過分だけ |"
        " Snapshot からの複製は容量を消費する。**EC2 インスタンスタイプごとに EBS の帯域と"
        " IOPS の上限がある** |"
    )
    lines.append(
        "| EBS + FSx for ONTAP | FlexClone の作成がメタデータ操作で済む。SnapMirror が使える。"
        " 同じボリュームに NFS / SMB / iSCSI で到達できる |"
        " **SSD・IOPS・スループットは確保した量で課金され、空きも請求される。**"
        " 階層化すると容量プールのリクエスト課金が乗る。スループット容量が上限になる |"
    )
    lines.append("| EBS io2 | 確保した IOPS が保証される | GB 単価と IOPS 単価がどちらも高い |")
    lines.append("")
    lines.append("**容量単価の比較だけでは決まりません。** ただし逆に、運用機能を理由に")
    lines.append("容量単価の差を無視することもできません。**どちらの側も、この表の右列を")
    lines.append("読んでから決める必要があります。**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本レポートはサンプル構成の定価計算であり、実際の請求額とは異なります。*")
    lines.append("*最新料金: https://aws.amazon.com/fsx/netapp-ontap/pricing/*")

    return "\n".join(lines)


# ==============================================================================
# メイン
# ==============================================================================


def main():
    parser = argparse.ArgumentParser(description="EBS vs FSx for ONTAP コスト比較")
    parser.add_argument("--data-size", type=float, default=500, help="データサイズ (GB)")
    parser.add_argument(
        "--throughput", type=int, default=512, help="FSx for ONTAP スループット (MB/s)"
    )
    parser.add_argument(
        "--efficiency",
        type=float,
        default=0.65,
        help="Storage Efficiency 後の実効率 (0.65 = 35%%削減)",
    )
    parser.add_argument("--iops", type=int, default=5000, help="必要 IOPS")
    parser.add_argument(
        "--pool-requests-millions",
        type=float,
        default=0.0,
        help="容量プールへの月間リクエスト数（百万単位）。階層化する場合は必ず指定する",
    )
    parser.add_argument(
        "--shrink-provisioned",
        action="store_true",
        help="効率化で空いた分だけ確保容量を下げる操作を行った前提で計算する",
    )
    parser.add_argument("--output", type=str, default=None, help="出力ファイルパス (.md)")
    parser.add_argument("--json", action="store_true", help="JSON 形式でも出力")

    args = parser.parse_args()

    report = generate_comparison_report(
        data_size_gb=args.data_size,
        throughput_mbps=args.throughput,
        efficiency_ratio=args.efficiency,
        iops=args.iops,
        pool_requests_millions=args.pool_requests_millions,
        shrink_provisioned=args.shrink_provisioned,
    )

    print(report)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"\n✅ レポート保存: {args.output}")

    if args.json:
        results = {
            "fsxn": calculate_fsxn_cost(
                args.data_size,
                args.throughput,
                efficiency_ratio=args.efficiency,
                iops=args.iops,
                pool_requests_millions=args.pool_requests_millions,
                shrink_provisioned=args.shrink_provisioned,
            ),
            "ebs_gp3": calculate_ebs_gp3_cost(
                args.data_size, iops=args.iops, throughput_mbps=args.throughput
            ),
            "ebs_io2": calculate_ebs_io2_cost(args.data_size, iops=args.iops),
        }
        json_path = (args.output or "cost-comparison") + ".json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"✅ JSON 保存: {json_path}")


if __name__ == "__main__":
    main()
