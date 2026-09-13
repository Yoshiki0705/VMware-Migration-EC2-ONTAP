#!/usr/bin/env python3
"""EBS のみ構成と EBS + FSx for ONTAP 構成の月額ストレージコスト比較。

**これはサンプル構成の定価計算であって、本番の見積りではない。** 割引、既存のコミットメント、
Savings Plans、EDP を含まない。判断の前に AWS Pricing Calculator で確認する。

単価はハードコードしていない値ではなく、**AWS Price List API から取得して固定した値**である。
各単価は `Rate` に SKU と usagetype を持っており、`--check-prices` で API と突き合わせられる。
**単価が動いたらこのスクリプトは落ちる**（`make prices` / CI ではなく手動実行。API 呼び出しに
認証が要るため）。

課金の区分（確保した量 / 消費した量）は FSx for ONTAP Adoption Playbook の
`docs/ja/domains/cost/notes/provisioned-versus-consumed.md` に従う。**効率化は既定では請求を
下げない。** SSD は確保した量で課金されるため、確保容量を下げるまで請求は変わらない。

Usage:
    python3 cost_comparison.py --data-size 1000 --throughput 512 --iops 5000
    python3 cost_comparison.py --deployment SINGLE_AZ_1 --data-size 1000
    # 階層化するなら読みと書きのリクエスト数を渡す（単価が 12.7 倍違う）
    python3 cost_comparison.py --data-size 1000 --pool-read-requests-millions 500 \
        --pool-write-requests-millions 20
    # 固定した単価を API と突き合わせる（AWS 認証が必要）
    python3 cost_comparison.py --check-prices

出典:
    https://aws.amazon.com/fsx/netapp-ontap/pricing/
    https://aws.amazon.com/ebs/pricing/
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

# ==============================================================================
# 固定した単価
#
# **すべて AWS Price List API から取得した値で、記憶や料金ページの読み取りではない。**
# 取得日 2026-09-13、リージョン ap-northeast-1。
#   FSx for ONTAP: effectiveDate 2026-07-01、publicationDate 2026-09-11
#   EBS:           effectiveDate 2026-09-01、publicationDate 2026-09-10
#
# `api_price` は API が返す `pricePerUnit.USD` をそのまま入れている。**単位換算を挟まない。**
# 換算が必要なものは `per_api_unit` に書き、計算側で割る（gp3 のスループットは API が
# GiBps-mo で返すため 1024 で割る）。こうしておくと `--check-prices` が API の値と
# 1 対 1 で比較できる。
# ==============================================================================

PRICING_PINNED_AT = "2026-09-13"
REGION = "ap-northeast-1"


@dataclass(frozen=True)
class Rate:
    """単価 1 件と、その出所。

    Attributes:
        api_price: Price List API の `pricePerUnit.USD`。**加工しない。**
        api_unit: API が返す単位。換算の有無を読む側が判断できるように残す。
        sku: Price List API の SKU。`--check-prices` の照合キー。
        usagetype: 請求明細に出る usagetype。CUR と突き合わせるときに使う。
        label: レポートに出す名前。
    """

    api_price: float
    api_unit: str
    sku: str
    usagetype: str
    label: str


# FSx for ONTAP。deploymentOption ごとに単価が違う。**割引は一律ではない。** 容量と IOPS は
# Single-AZ が Multi-AZ の半額だが、**スループット容量は $0.906 対 $1.511 で 60.0%**、
# リクエストは同額である。一律の係数で片方から他方を出すと、スループットの比重が大きい構成でずれる。
FSXN_RATES: dict[str, dict[str, Rate]] = {
    "MULTI_AZ_1": {
        "ssd": Rate(0.300, "GB-Mo", "2PXSTVP3HEKU8FV8", "APN1-Storage.MAZ:SSD", "SSD ストレージ"),
        "capacity_pool": Rate(
            0.0476, "GB-Mo", "KXRM2FE8UABECEM2", "APN1-Storage.MAZ:CPoolStd", "容量プール"
        ),
        "throughput": Rate(
            1.511, "MiBps-Mo", "PVDTPUSDBJVBU4W2", "APN1-ThroughputCapacity.MAZ", "スループット容量"
        ),
        "ssd_iops": Rate(
            0.0408, "IOPS-Mo", "77JR26CMAGF5TNRY", "APN1-ProvisionedSSDIOPS.MAZ", "超過 SSD IOPS"
        ),
        "pool_read": Rate(
            0.00000037,
            "Operations",
            "N5BXQP9JNKREQCUC",
            "APN1-Requests.MAZ:CPoolStdRd",
            "容量プール読みリクエスト",
        ),
        "pool_write": Rate(
            0.0000047,
            "Operations",
            "QKKB284PSUQHM3WN",
            "APN1-Requests.MAZ:CPoolStdWr",
            "容量プール書きリクエスト",
        ),
    },
    "SINGLE_AZ_1": {
        "ssd": Rate(
            0.150, "GB-Mo", "4M9T5U5EGURPEF6X", "APN1-Storage.SAZ_2N:SSD", "SSD ストレージ"
        ),
        "capacity_pool": Rate(
            0.0238, "GB-Mo", "M95Z6GZYDU67JSB2", "APN1-Storage.SAZ_2N:CPoolStd", "容量プール"
        ),
        "throughput": Rate(
            0.906,
            "MiBps-Mo",
            "79GNR3MAFQUJHR6Q",
            "APN1-ThroughputCapacity.SAZ_2N",
            "スループット容量",
        ),
        "ssd_iops": Rate(
            0.0204,
            "IOPS-Mo",
            "RYMUBZ5MYT5X5QGY",
            "APN1-ProvisionedSSDIOPS.SAZ_2N",
            "超過 SSD IOPS",
        ),
        "pool_read": Rate(
            0.00000037,
            "Operations",
            "HVEJR9UHQRCHAYC6",
            "APN1-Requests.SAZ_2N:CPoolStdRd",
            "容量プール読みリクエスト",
        ),
        "pool_write": Rate(
            0.0000047,
            "Operations",
            "7K57GQR4D3UCS6S6",
            "APN1-Requests.SAZ_2N:CPoolStdWr",
            "容量プール書きリクエスト",
        ),
    },
}

# **3 IOPS/GB までは SSD 容量に含まれる。** 超過分だけが課金対象で、
# 「IOPS を上げたら必ず課金が増える」は誤り。
SSD_INCLUDED_IOPS_PER_GB = 3

EBS_RATES: dict[str, Rate] = {
    "gp3_storage": Rate(0.096, "GB-Mo", "C8Y3GJZBQTH8T5JV", "APN1-EBS:VolumeUsage.gp3", "gp3 容量"),
    "gp3_iops": Rate(
        0.006, "IOPS-Mo", "7TFGMV47Q2PEQ9W7", "APN1-EBS:VolumeP-IOPS.gp3", "gp3 超過 IOPS"
    ),
    # **API は GiBps-mo で返す。** $49.152 / 1024 = $0.048 per MiBps-Mo。
    "gp3_throughput": Rate(
        49.152,
        "GiBps-mo",
        "PCKHHBTPD7TEQ3K4",
        "APN1-EBS:VolumeP-Throughput.gp3",
        "gp3 超過スループット",
    ),
    "io2_storage": Rate(
        0.142, "GB-month", "X64MAFXTT3P6QD64", "APN1-EBS:VolumeUsage.io2", "io2 容量"
    ),
    "io2_iops_tier1": Rate(
        0.074, "IOPS-Mo", "93STHNX46RXXQJAT", "APN1-EBS:VolumeP-IOPS.io2", "io2 IOPS（〜32,000）"
    ),
    "io2_iops_tier2": Rate(
        0.0518,
        "IOPS-Mo",
        "R6R2MQNR2BKDVM3W",
        "APN1-EBS:VolumeP-IOPS.io2.tier2",
        "io2 IOPS（32,001〜64,000）",
    ),
    "io2_iops_tier3": Rate(
        0.03626,
        "IOPS-Mo",
        "T45SQDJUGF4D77XT",
        "APN1-EBS:VolumeP-IOPS.io2.tier3",
        "io2 IOPS（64,000 超）",
    ),
}

GP3_BASELINE_IOPS = 3000
GP3_BASELINE_THROUGHPUT_MBPS = 125
IO2_TIER1_LIMIT = 32_000
IO2_TIER2_LIMIT = 64_000

# ボリューム 1 本あたりの上限。**値段が付くことと出せることは別である。** 上限を超えた構成に
# 金額を出すと、EBS 側に実現できない安い値が並ぶ。
# 出典: https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html
#       gp3 は IOPS 3,000〜80,000、スループット 125〜2,000 MiB/s、
#       かつ **スループットは確保 IOPS 1 につき 0.25 MiB/s まで**（2,000 MiB/s には 8,000 IOPS 必要）
GP3_MAX_IOPS = 80_000
GP3_MAX_THROUGHPUT_MBPS = 2_000
GP3_THROUGHPUT_PER_IOPS = 0.25
# io2 は 100〜256,000 IOPS。**256,000 は Nitro 世代のみで、それ以外は 32,000 まで。**
# 出典: https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html
IO2_MAX_IOPS_NITRO = 256_000
IO2_MAX_IOPS_NON_NITRO = 32_000

# 両方の構成に共通で載る OS ディスク。差分に効かないが、合計を見たときの絶対額に効く。
OS_DISK_GB = 50


# ==============================================================================
# 計算
# ==============================================================================


def gp3_throughput_per_mbps(rates: dict[str, Rate] | None = None) -> float:
    """gp3 の超過スループット単価を MiBps あたりに換算する。

    API が `GiBps-mo` で返すため 1024 で割る。**この換算を忘れると 1024 倍になる。**
    """
    r = (rates or EBS_RATES)["gp3_throughput"]
    return r.api_price / 1024


def io2_iops_cost(iops: int, rates: dict[str, Rate] | None = None) -> float:
    """io2 の IOPS 課金を階層で計算する。

    **単価は階層で下がる。** 32,000 まで、32,001〜64,000、64,000 超で別の単価が適用される。
    一律で最初の単価をかけると高 IOPS 側を過大に見積もる。
    """
    r = rates or EBS_RATES
    tier1 = min(iops, IO2_TIER1_LIMIT)
    tier2 = min(max(iops - IO2_TIER1_LIMIT, 0), IO2_TIER2_LIMIT - IO2_TIER1_LIMIT)
    tier3 = max(iops - IO2_TIER2_LIMIT, 0)
    return (
        tier1 * r["io2_iops_tier1"].api_price
        + tier2 * r["io2_iops_tier2"].api_price
        + tier3 * r["io2_iops_tier3"].api_price
    )


def calculate_fsxn_cost(
    data_size_gb: float,
    throughput_mbps: int,
    deployment: str = "MULTI_AZ_1",
    ssd_ratio: float = 1.0,
    efficiency_ratio: float = 1.0,
    iops: int = 0,
    pool_read_requests_millions: float = 0.0,
    pool_write_requests_millions: float = 0.0,
    shrink_provisioned: bool = False,
) -> dict:
    """FSx for ONTAP の月額コスト。

    **効率化は請求を下げない。** 重複排除と圧縮はデータを縮めるが SSD は確保した量で課金される
    ので、既定では `efficiency_ratio` を確保容量に反映させず「同じ確保容量にどれだけ論理データが
    入るか」としてだけ報告する。確保容量を実際に下げる操作をモデル化する場合に
    `shrink_provisioned=True` を渡す。

    Args:
        data_size_gb: 論理データサイズ (GB)
        throughput_mbps: 確保するスループット (MB/s)
        deployment: `MULTI_AZ_1` または `SINGLE_AZ_1`
        ssd_ratio: SSD に確保する割合。残りは容量プールに置く前提
        efficiency_ratio: 効率化後の物理データ率 (0.6 = 40% 削減)
        iops: 必要 IOPS。3 IOPS/GB を超えた分だけが課金対象
        pool_read_requests_millions: 容量プールへの月間読みリクエスト（百万単位）
        pool_write_requests_millions: 同・書き。**読みの 12.7 倍の単価である**
        shrink_provisioned: 効率化で空いた分だけ確保容量を下げる場合に True
    """
    if deployment not in FSXN_RATES:
        raise ValueError(f"unknown deployment: {deployment}. {sorted(FSXN_RATES)} のいずれか")
    r = FSXN_RATES[deployment]

    provisioned_ssd_gb = data_size_gb * ssd_ratio
    if shrink_provisioned:
        provisioned_ssd_gb *= efficiency_ratio

    physical_size_gb = data_size_gb * efficiency_ratio
    capacity_pool_gb = max(0.0, physical_size_gb - provisioned_ssd_gb)

    ssd_cost = provisioned_ssd_gb * r["ssd"].api_price
    pool_cost = capacity_pool_gb * r["capacity_pool"].api_price
    read_cost = pool_read_requests_millions * 1_000_000 * r["pool_read"].api_price
    write_cost = pool_write_requests_millions * 1_000_000 * r["pool_write"].api_price
    throughput_cost = throughput_mbps * r["throughput"].api_price

    included_iops = int(provisioned_ssd_gb * SSD_INCLUDED_IOPS_PER_GB)
    extra_iops = max(0, iops - included_iops)
    iops_cost = extra_iops * r["ssd_iops"].api_price

    total = ssd_cost + pool_cost + read_cost + write_cost + throughput_cost + iops_cost
    headroom = provisioned_ssd_gb - min(physical_size_gb, provisioned_ssd_gb)

    return {
        "service": f"FSx for ONTAP ({deployment})",
        "deployment": deployment,
        "logical_data_gb": data_size_gb,
        "physical_data_gb": round(physical_size_gb, 1),
        "provisioned_ssd_gb": round(provisioned_ssd_gb, 1),
        "efficiency_headroom_gb": round(headroom, 1),
        "efficiency_reduces_bill": shrink_provisioned,
        "capacity_pool_gb": round(capacity_pool_gb, 1),
        "throughput_mbps": throughput_mbps,
        "included_iops": included_iops,
        "billed_extra_iops": extra_iops,
        "pool_read_requests_millions": pool_read_requests_millions,
        "pool_write_requests_millions": pool_write_requests_millions,
        "cost_ssd": round(ssd_cost, 2),
        "cost_capacity_pool": round(pool_cost, 2),
        "cost_pool_read_requests": round(read_cost, 2),
        "cost_pool_write_requests": round(write_cost, 2),
        "cost_throughput": round(throughput_cost, 2),
        "cost_extra_iops": round(iops_cost, 2),
        "total_monthly_usd": round(total, 2),
    }


def gp3_violations(iops: int, throughput_mbps: float) -> list[str]:
    """gp3 のボリューム 1 本あたりの上限に反する点を返す。空なら実現可能。"""
    v: list[str] = []
    if iops > GP3_MAX_IOPS:
        v.append(f"IOPS {iops:,} がボリューム 1 本の上限 {GP3_MAX_IOPS:,} を超える")
    if throughput_mbps > GP3_MAX_THROUGHPUT_MBPS:
        v.append(
            f"スループット {throughput_mbps:,.0f} MB/s が上限 "
            f"{GP3_MAX_THROUGHPUT_MBPS:,} MiB/s を超える"
        )
    max_by_iops = iops * GP3_THROUGHPUT_PER_IOPS
    if throughput_mbps > max_by_iops:
        v.append(
            f"スループット {throughput_mbps:,.0f} MB/s には確保 IOPS "
            f"{int(throughput_mbps / GP3_THROUGHPUT_PER_IOPS):,} 以上が必要"
            f"（IOPS 1 につき {GP3_THROUGHPUT_PER_IOPS} MiB/s まで。いまは {iops:,}）"
        )
    return v


def io2_violations(iops: int, nitro: bool = True) -> list[str]:
    """io2 のボリューム 1 本あたりの IOPS 上限に反する点を返す。"""
    cap = IO2_MAX_IOPS_NITRO if nitro else IO2_MAX_IOPS_NON_NITRO
    if iops > cap:
        kind = "Nitro 世代" if nitro else "Nitro 世代以外"
        return [f"IOPS {iops:,} が{kind}の上限 {cap:,} を超える"]
    return []


def calculate_ebs_gp3_cost(
    data_size_gb: float,
    iops: int = GP3_BASELINE_IOPS,
    throughput_mbps: int = GP3_BASELINE_THROUGHPUT_MBPS,
) -> dict:
    """EBS gp3 の月額コスト。3,000 IOPS と 125 MB/s まではベースラインで追加課金が無い。

    **上限を超えていても金額は返す。** ただし `violations` に理由を入れ、`feasible` を False に
    する。金額だけを見て実現できない構成を比較に並べないため。
    """
    storage_cost = data_size_gb * EBS_RATES["gp3_storage"].api_price
    extra_iops = max(0, iops - GP3_BASELINE_IOPS)
    iops_cost = extra_iops * EBS_RATES["gp3_iops"].api_price
    extra_throughput = max(0, throughput_mbps - GP3_BASELINE_THROUGHPUT_MBPS)
    throughput_cost = extra_throughput * gp3_throughput_per_mbps()
    total = storage_cost + iops_cost + throughput_cost

    violations = gp3_violations(iops, throughput_mbps)

    return {
        "service": "EBS gp3",
        "data_gb": data_size_gb,
        "provisioned_iops": iops,
        "provisioned_throughput_mbps": throughput_mbps,
        "billed_extra_iops": extra_iops,
        "billed_extra_throughput_mbps": extra_throughput,
        "feasible": not violations,
        "violations": violations,
        "cost_storage": round(storage_cost, 2),
        "cost_extra_iops": round(iops_cost, 2),
        "cost_extra_throughput": round(throughput_cost, 2),
        "total_monthly_usd": round(total, 2),
    }


def calculate_ebs_io2_cost(data_size_gb: float, iops: int = 10000, nitro: bool = True) -> dict:
    """EBS io2 の月額コスト。IOPS は階層で単価が下がる。"""
    storage_cost = data_size_gb * EBS_RATES["io2_storage"].api_price
    iops_cost = io2_iops_cost(iops)
    total = storage_cost + iops_cost
    violations = io2_violations(iops, nitro=nitro)

    return {
        "service": "EBS io2",
        "data_gb": data_size_gb,
        "provisioned_iops": iops,
        "feasible": not violations,
        "violations": violations,
        "cost_storage": round(storage_cost, 2),
        "cost_iops": round(iops_cost, 2),
        "total_monthly_usd": round(total, 2),
    }


# ==============================================================================
# 台数を変えたときの比較
# ==============================================================================


def compare_at_scale(
    vm_count: int,
    data_gb_per_vm: float,
    aggregate_throughput_mbps: int,
    aggregate_iops: int,
    deployment: str = "MULTI_AZ_1",
    efficiency_ratio: float = 1.0,
) -> dict:
    """VM 台数を変えて 2 構成を比較する。

    **1 台での比較は FSx for ONTAP に最も不利な形である。** スループット容量はファイルシステム
    単位で 1 回買うが、EBS はボリュームごとに買う。一方で **EBS はボリュームごとに 3,000 IOPS と
    125 MB/s が無料で付く**ため、同じ総量を多くのボリュームに分けると EBS 側が下がる。
    どちらに転ぶかは台数と総量で決まるので、片方だけを示さない。

    総量（`aggregate_*`）は構成全体で必要な量とし、EBS 側は台数で等分する。

    Args:
        vm_count: 移行する VM 台数
        data_gb_per_vm: 1 台あたりのデータ容量 (GB)
        aggregate_throughput_mbps: 構成全体で必要なスループット (MB/s)
        aggregate_iops: 構成全体で必要な IOPS
        deployment: FSx for ONTAP の配置
        efficiency_ratio: 効率化後の物理データ率（確保容量は下げない）
    """
    if vm_count < 1:
        raise ValueError("vm_count は 1 以上")

    total_data_gb = data_gb_per_vm * vm_count
    per_vm_throughput = aggregate_throughput_mbps / vm_count
    per_vm_iops = aggregate_iops // vm_count

    os_disk_total = OS_DISK_GB * EBS_RATES["gp3_storage"].api_price * vm_count

    # 構成 A: 台数分の gp3 ボリューム。各ボリュームに無料ベースラインが付く
    gp3_one = calculate_ebs_gp3_cost(
        data_gb_per_vm, iops=per_vm_iops, throughput_mbps=int(per_vm_throughput)
    )
    ebs_total = os_disk_total + gp3_one["total_monthly_usd"] * vm_count

    # 構成 B: 1 つのファイルシステムを共有。スループット容量は 1 回だけ買う
    fsxn = calculate_fsxn_cost(
        total_data_gb,
        aggregate_throughput_mbps,
        deployment=deployment,
        efficiency_ratio=efficiency_ratio,
        iops=aggregate_iops,
    )
    fsxn_total = os_disk_total + fsxn["total_monthly_usd"]

    return {
        "vm_count": vm_count,
        "total_data_gb": total_data_gb,
        "per_vm_throughput_mbps": round(per_vm_throughput, 1),
        "per_vm_iops": per_vm_iops,
        "ebs_only_feasible": gp3_one["feasible"],
        "ebs_only_violations": gp3_one["violations"],
        "ebs_only_monthly_usd": round(ebs_total, 2),
        "fsxn_monthly_usd": round(fsxn_total, 2),
        "difference_usd": round(fsxn_total - ebs_total, 2),
        "fsxn_is_cheaper": fsxn_total < ebs_total,
    }


def find_crossover(
    data_gb_per_vm: float,
    aggregate_throughput_mbps: int,
    aggregate_iops: int,
    deployment: str = "MULTI_AZ_1",
    max_vms: int = 200,
) -> int | None:
    """FSx 構成が EBS のみ構成より安くなる最小の台数。無ければ None。

    **None が返ることは「見つからなかった」であって「存在しない」ではない。** 探索は
    `max_vms` までで、容量単価の差が支配的な構成では台数を増やしても逆転しない。
    """
    for n in range(1, max_vms + 1):
        if compare_at_scale(
            n, data_gb_per_vm, aggregate_throughput_mbps, aggregate_iops, deployment
        )["fsxn_is_cheaper"]:
            return n
    return None


# ==============================================================================
# 単価の照合
# ==============================================================================


def check_prices(region: str = REGION) -> list[str]:
    """固定した単価を Price List API と突き合わせ、ずれを文字列で返す。

    **空リストが返れば一致。** API 呼び出しに AWS 認証が必要なので CI では走らせない。
    Price List API のエンドポイントは us-east-1 と ap-south-1 にしかない。
    """
    import boto3  # 照合時だけ必要。レポート生成には要らない

    client = boto3.client("pricing", region_name="us-east-1")
    drift: list[str] = []

    pins: list[tuple[str, str, Rate]] = []
    for deployment, rates in FSXN_RATES.items():
        for key, rate in rates.items():
            pins.append((f"AmazonFSx/{deployment}/{key}", "AmazonFSx", rate))
    for key, rate in EBS_RATES.items():
        pins.append((f"AmazonEC2/{key}", "AmazonEC2", rate))

    for name, service_code, rate in pins:
        resp = client.get_products(
            ServiceCode=service_code,
            Filters=[
                {"Type": "TERM_MATCH", "Field": "usagetype", "Value": rate.usagetype},
                {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            ],
            MaxResults=10,
        )
        found: list[tuple[str, float]] = []
        for raw in resp.get("PriceList", []):
            doc = json.loads(raw)
            sku = doc["product"]["sku"]
            for term in doc.get("terms", {}).get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    found.append((sku, float(dim["pricePerUnit"]["USD"])))

        match = [price for sku, price in found if sku == rate.sku]
        if not match:
            drift.append(
                f"{name}: SKU {rate.sku} が usagetype {rate.usagetype} で見つからない"
                f"（見つかった SKU: {sorted({s for s, _ in found}) or 'なし'}）"
            )
            continue
        live = match[0]
        if abs(live - rate.api_price) > 1e-9:
            drift.append(
                f"{name}: 固定 {rate.api_price} != API {live}"
                f"（{rate.api_unit}, SKU {rate.sku}, usagetype {rate.usagetype}）"
            )
    return drift


# ==============================================================================
# レポート生成
# ==============================================================================


def generate_comparison_report(
    data_size_gb: float,
    throughput_mbps: int,
    efficiency_ratio: float,
    iops: int,
    deployment: str = "MULTI_AZ_1",
    pool_read_requests_millions: float = 0.0,
    pool_write_requests_millions: float = 0.0,
    shrink_provisioned: bool = False,
) -> str:
    """比較レポートを Markdown で生成する。"""
    fsxn = calculate_fsxn_cost(
        data_size_gb,
        throughput_mbps,
        deployment=deployment,
        efficiency_ratio=efficiency_ratio,
        iops=iops,
        pool_read_requests_millions=pool_read_requests_millions,
        pool_write_requests_millions=pool_write_requests_millions,
        shrink_provisioned=shrink_provisioned,
    )
    ebs_gp3 = calculate_ebs_gp3_cost(data_size_gb, iops=iops, throughput_mbps=throughput_mbps)
    ebs_io2 = calculate_ebs_io2_cost(data_size_gb, iops=iops)
    os_disk_cost = OS_DISK_GB * EBS_RATES["gp3_storage"].api_price

    total_a = os_disk_cost + ebs_gp3["total_monthly_usd"]
    total_b = os_disk_cost + fsxn["total_monthly_usd"]
    total_c = os_disk_cost + ebs_io2["total_monthly_usd"]

    o: list[str] = []
    a = o.append
    a("# ストレージコスト比較レポート")
    a("")
    a(f"**リージョン**: {REGION}（東京） / **FSx for ONTAP の配置**: {deployment}")
    a(f"**論理データサイズ**: {data_size_gb} GB / **必要 IOPS**: {iops}")
    a(f"**必要スループット**: {throughput_mbps} MB/s")
    a(f"**効率化の想定削減率**: {round((1 - efficiency_ratio) * 100)}%")
    a(
        f"**容量プールへのリクエスト**: 読み {pool_read_requests_millions} 百万 / "
        f"書き {pool_write_requests_millions} 百万"
    )
    a("")
    a("> **これはサンプル構成の定価計算であって、本番の見積りではありません。**")
    a(f"> 単価は AWS Price List API から {PRICING_PINNED_AT} に取得して固定した値です。")
    a("> 割引、既存のコミットメント、Savings Plans、EDP を含みません。")
    a("> **判断の前に AWS Pricing Calculator で確認してください。**")
    a("")
    a("> **効率化は既定では請求を下げません。** 重複排除と圧縮はデータを縮めますが、")
    a("> SSD は確保した量で課金されます。確保容量を実際に下げるまで請求は変わりません。")
    if shrink_provisioned:
        a("> この計算では確保容量を下げる操作を行った前提にしています。")
    a("")
    a("## 構成比較")
    a("")
    a("| 項目 | 構成 A: EBS gp3 のみ | 構成 B: EBS + FSx for ONTAP | 構成 C: EBS io2 |")
    a("|---|---|---|---|")
    a(f"| OS ディスク | EBS gp3 {OS_DISK_GB}GB | EBS gp3 {OS_DISK_GB}GB | EBS gp3 {OS_DISK_GB}GB |")
    a(
        f"| データディスク | EBS gp3 {data_size_gb}GB | FSx for ONTAP iSCSI {data_size_gb}GB "
        f"| EBS io2 {data_size_gb}GB |"
    )
    a(
        f"| IOPS | {iops}（確保。{GP3_BASELINE_IOPS} まで込み） "
        f"| 3 IOPS/GB 込み + 超過 {fsxn['billed_extra_iops']} | {iops}（確保。階層単価） |"
    )
    a("| Snapshot | EBS Snapshot（S3 に保存） | ONTAP Snapshot（ボリューム内） | EBS Snapshot |")
    a(
        "| クローン | Snapshot から新ボリューム（容量を消費） | FlexClone（作成はメタデータのみ） "
        "| Snapshot から新ボリューム |"
    )
    a("| レプリケーション | Snapshot コピー | SnapMirror | Snapshot コピー |")
    a(
        f"| 重複排除・圧縮 | なし | あり（{round((1 - efficiency_ratio) * 100)}% 削減想定。"
        "**確保容量を下げないと請求は変わらない**） | なし |"
    )
    a(
        "| 課金の性質 | 確保した量 | **SSD・IOPS・スループットは確保した量。容量プールは消費量 + "
        "リクエスト** | 確保した量 |"
    )
    a("")
    a("## 月額の内訳")
    a("")
    a("### 構成 A: EBS gp3 のみ")
    a("")
    a(f"- OS ディスク: ${os_disk_cost:.2f}")
    a(f"- データ容量: ${ebs_gp3['cost_storage']:.2f}")
    a(f"- 超過 IOPS（{ebs_gp3['billed_extra_iops']}）: ${ebs_gp3['cost_extra_iops']:.2f}")
    a(
        f"- 超過スループット（{ebs_gp3['billed_extra_throughput_mbps']} MB/s）: "
        f"${ebs_gp3['cost_extra_throughput']:.2f}"
    )
    a(f"- **合計: ${total_a:.2f}/月**")
    if not ebs_gp3["feasible"]:
        a("")
        a("> **この構成はボリューム 1 本では出せません。** 金額は参考にできません。")
        for v in ebs_gp3["violations"]:
            a(f"> - {v}")
        a("> ボリュームを分けるか、`--vm-count` で台数に分けた比較を見てください。")
    a("")
    a("### 構成 B: EBS (OS) + FSx for ONTAP (Data)")
    a("")
    a(f"- OS ディスク（EBS gp3）: ${os_disk_cost:.2f}")
    a(f"- 確保 SSD（{fsxn['provisioned_ssd_gb']} GB）: ${fsxn['cost_ssd']:.2f}")
    a(f"- 容量プール（{fsxn['capacity_pool_gb']} GB）: ${fsxn['cost_capacity_pool']:.2f}")
    a(f"- スループット容量（{throughput_mbps} MB/s）: ${fsxn['cost_throughput']:.2f}")
    a(
        f"- 超過 IOPS（{fsxn['billed_extra_iops']}。{fsxn['included_iops']} は 3 IOPS/GB として"
        f"込み）: ${fsxn['cost_extra_iops']:.2f}"
    )
    a(
        f"- 容量プールの読みリクエスト（{pool_read_requests_millions} 百万）: "
        f"${fsxn['cost_pool_read_requests']:.2f}"
    )
    a(
        f"- 容量プールの書きリクエスト（{pool_write_requests_millions} 百万）: "
        f"${fsxn['cost_pool_write_requests']:.2f}"
    )
    a(f"- **合計: ${total_b:.2f}/月**")
    a(
        f"- 確保 SSD {fsxn['provisioned_ssd_gb']} GB に対し物理データは "
        f"{fsxn['physical_data_gb']} GB。**空き {fsxn['efficiency_headroom_gb']} GB は"
        "請求対象のまま**"
    )
    a("")
    a("### 構成 C: EBS io2")
    a("")
    a(f"- OS ディスク（EBS gp3）: ${os_disk_cost:.2f}")
    a(f"- データ容量: ${ebs_io2['cost_storage']:.2f}")
    a(f"- IOPS（{iops}、階層単価）: ${ebs_io2['cost_iops']:.2f}")
    a(f"- **合計: ${total_c:.2f}/月**")
    if not ebs_io2["feasible"]:
        a("")
        a("> **この構成はボリューム 1 本では出せません。**")
        for v in ebs_io2["violations"]:
            a(f"> - {v}")
    a("")
    a("## 合計の比較")
    a("")
    a("| 構成 | 月額 | 年額 | 対構成 A 比 |")
    a("|---|---|---|---|")
    a(f"| A: EBS gp3 のみ | ${total_a:,.2f} | ${total_a * 12:,.2f} | — |")
    a(
        f"| B: EBS + FSx for ONTAP | ${total_b:,.2f} | ${total_b * 12:,.2f} "
        f"| {((total_b / total_a) - 1) * 100:+.1f}% |"
    )
    a(
        f"| C: EBS io2 | ${total_c:,.2f} | ${total_c * 12:,.2f} "
        f"| {((total_c / total_a) - 1) * 100:+.1f}% |"
    )
    a("")
    a("## 何と引き換えに何を得るか")
    a("")
    a("**片側だけを並べると判断できません。** 選択ごとに、下がるものと受け入れるものを")
    a("対称に置きます。")
    a("")
    a("| 選択 | 得られるもの | 受け入れるもの |")
    a("|---|---|---|")
    a(
        "| EBS gp3 のみ | 課金要素が少なく見積りが単純。追加 IOPS とスループットは超過分だけ "
        "| Snapshot からの複製は容量を消費する。**EC2 インスタンスタイプごとに EBS の帯域と "
        "IOPS の上限がある** |"
    )
    a(
        "| EBS + FSx for ONTAP | FlexClone の作成がメタデータ操作で済む。SnapMirror が使える。"
        "同じボリュームに NFS / SMB / iSCSI で到達できる "
        "| **SSD・IOPS・スループットは確保した量で課金され、空きも請求される。** "
        "階層化すると容量プールのリクエスト課金が乗る。スループット容量が上限になる |"
    )
    a(
        "| EBS io2 | 確保した IOPS が保証される | GB 単価が高い。"
        "**IOPS 単価は階層で下がるので、低 IOPS では割高になりやすい** |"
    )
    a("")
    a("**容量単価の比較だけでは決まりません。** ただし逆に、運用機能を理由に容量単価の差を")
    a("無視することもできません。**どちらの側も、この表の右列を読んでから決める必要があります。**")
    a("")
    a("## 単価の出所")
    a("")
    a(f"すべて AWS Price List API から {PRICING_PINNED_AT} に取得した値です。")
    a("`python3 scripts/cost_comparison.py --check-prices` で API と突き合わせられます。")
    a("")
    a("| 項目 | 単価 | 単位 | usagetype |")
    a("|---|---|---|---|")
    for rate in FSXN_RATES[deployment].values():
        a(
            f"| FSx for ONTAP {rate.label} | ${rate.api_price} | {rate.api_unit} | `{rate.usagetype}` |"
        )
    for rate in EBS_RATES.values():
        a(f"| EBS {rate.label} | ${rate.api_price} | {rate.api_unit} | `{rate.usagetype}` |")
    a("")
    a("**gp3 の超過スループットは API が `GiBps-mo` で返します。**")
    a(f"MiBps あたりは ${gp3_throughput_per_mbps():.3f} です（1024 で割った値）。")
    a("")
    a("---")
    a("")
    a("*本レポートはサンプル構成の定価計算であり、実際の請求額とは異なります。*")
    a("*最新料金: <https://aws.amazon.com/fsx/netapp-ontap/pricing/>*")
    return "\n".join(o)


# ==============================================================================
# メイン
# ==============================================================================


def main() -> int:
    p = argparse.ArgumentParser(description="EBS と FSx for ONTAP のストレージコスト比較")
    p.add_argument("--data-size", type=float, default=1000, help="論理データサイズ (GB)")
    p.add_argument("--throughput", type=int, default=512, help="FSx のスループット容量 (MB/s)")
    p.add_argument(
        "--deployment",
        choices=sorted(FSXN_RATES),
        default="MULTI_AZ_1",
        help="FSx for ONTAP の配置。Single-AZ は容量と IOPS が半額、スループット容量は約 60%%",
    )
    p.add_argument(
        "--efficiency", type=float, default=0.65, help="効率化後の実効率 (0.65 = 35%% 削減)"
    )
    p.add_argument("--iops", type=int, default=5000, help="必要 IOPS")
    p.add_argument(
        "--pool-read-requests-millions",
        type=float,
        default=0.0,
        help="容量プールへの月間読みリクエスト（百万単位）",
    )
    p.add_argument(
        "--pool-write-requests-millions",
        type=float,
        default=0.0,
        help="容量プールへの月間書きリクエスト（百万単位）。読みの 12.7 倍の単価",
    )
    p.add_argument(
        "--shrink-provisioned",
        action="store_true",
        help="効率化で空いた分だけ確保容量を下げた前提で計算する",
    )
    p.add_argument("--output", type=str, default=None, help="出力ファイルパス (.md)")
    p.add_argument("--json", action="store_true", help="JSON でも出力")
    p.add_argument(
        "--check-prices",
        action="store_true",
        help="固定した単価を Price List API と突き合わせる（AWS 認証が必要）",
    )
    args = p.parse_args()

    if args.check_prices:
        drift = check_prices()
        if drift:
            print(f"prices: {len(drift)} 件ずれている", file=sys.stderr)
            for d in drift:
                print(f"  {d}", file=sys.stderr)
            return 1
        total = sum(len(v) for v in FSXN_RATES.values()) + len(EBS_RATES)
        print(f"prices: {total} 件すべて API と一致（{REGION}、固定日 {PRICING_PINNED_AT}）")
        return 0

    report = generate_comparison_report(
        data_size_gb=args.data_size,
        throughput_mbps=args.throughput,
        efficiency_ratio=args.efficiency,
        iops=args.iops,
        deployment=args.deployment,
        pool_read_requests_millions=args.pool_read_requests_millions,
        pool_write_requests_millions=args.pool_write_requests_millions,
        shrink_provisioned=args.shrink_provisioned,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"レポートを {args.output} に書き出しました")
    else:
        print(report)

    if args.json:
        payload = {
            "pricing_pinned_at": PRICING_PINNED_AT,
            "region": REGION,
            "fsxn": calculate_fsxn_cost(
                args.data_size,
                args.throughput,
                deployment=args.deployment,
                efficiency_ratio=args.efficiency,
                iops=args.iops,
                pool_read_requests_millions=args.pool_read_requests_millions,
                pool_write_requests_millions=args.pool_write_requests_millions,
                shrink_provisioned=args.shrink_provisioned,
            ),
            "ebs_gp3": calculate_ebs_gp3_cost(
                args.data_size, iops=args.iops, throughput_mbps=args.throughput
            ),
            "ebs_io2": calculate_ebs_io2_cost(args.data_size, iops=args.iops),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
