"""cost_comparison.py の課金モデルの検査。

**単価そのものは検査しない。** 単価は `--check-prices` が Price List API と突き合わせる。
ここで固定するのは「単価をどう掛けるか」であり、過去に間違えた 3 点を対象にする。

  1. リクエスト課金の単位（API は 1 オペレーションあたり、入力は百万単位）
  2. 読みと書きで単価が違うこと
  3. io2 の IOPS 単価が階層で下がること

加えて、効率化が既定では請求を下げないこと（確保量課金）を固定する。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cost_comparison import (  # noqa: E402
    EBS_RATES,
    FSXN_RATES,
    GP3_BASELINE_IOPS,
    IO2_TIER1_LIMIT,
    IO2_TIER2_LIMIT,
    SSD_INCLUDED_IOPS_PER_GB,
    calculate_ebs_gp3_cost,
    calculate_ebs_io2_cost,
    calculate_fsxn_cost,
    compare_at_scale,
    find_crossover,
    generate_comparison_report,
    gp3_throughput_per_mbps,
    gp3_violations,
    io2_iops_cost,
    io2_violations,
)

# ---------------------------------------------------------------- リクエスト課金


def test_request_cost_uses_per_operation_rate_not_per_million():
    """**1 オペレーションあたりの単価に百万を掛ける。**

    以前は「百万リクエストあたり $0.0055」という値を持っており、実際の単価
    （読み $0.00037 / 1,000 = 1 オペレーション $0.00000037）と 3 桁ずれていた。
    """
    r = calculate_fsxn_cost(
        100, 128, ssd_ratio=0.0, pool_read_requests_millions=1.0, pool_write_requests_millions=0.0
    )
    rate = FSXN_RATES["MULTI_AZ_1"]["pool_read"].api_price
    assert r["cost_pool_read_requests"] == pytest.approx(1_000_000 * rate, abs=0.01)
    # 100 万回の読みで $0.37。桁を取り違えていないことを額でも固定する
    assert r["cost_pool_read_requests"] == pytest.approx(0.37, abs=0.01)


def test_write_requests_cost_more_than_reads():
    """**書きは読みより高い。** 単一の混合単価にまとめると、書きが多い経路を過小に見積もる。"""
    reads = calculate_fsxn_cost(100, 128, ssd_ratio=0.0, pool_read_requests_millions=10.0)
    writes = calculate_fsxn_cost(100, 128, ssd_ratio=0.0, pool_write_requests_millions=10.0)
    assert writes["cost_pool_write_requests"] > reads["cost_pool_read_requests"]
    ratio = writes["cost_pool_write_requests"] / reads["cost_pool_read_requests"]
    assert ratio == pytest.approx(0.0047 / 0.00037, rel=0.01)


# ---------------------------------------------------------------- 確保量課金


def test_efficiency_does_not_reduce_the_bill_by_default():
    """**効率化は既定では請求を下げない。** SSD は確保した量で課金される。"""
    full = calculate_fsxn_cost(1000, 512, efficiency_ratio=1.0)
    halved = calculate_fsxn_cost(1000, 512, efficiency_ratio=0.5)
    assert halved["cost_ssd"] == full["cost_ssd"]
    assert halved["efficiency_reduces_bill"] is False
    # 空きは報告されるが、請求対象のまま
    assert halved["efficiency_headroom_gb"] == pytest.approx(500.0)


def test_shrinking_provisioned_capacity_is_what_reduces_the_bill():
    shrunk = calculate_fsxn_cost(1000, 512, efficiency_ratio=0.5, shrink_provisioned=True)
    full = calculate_fsxn_cost(1000, 512, efficiency_ratio=1.0)
    assert shrunk["cost_ssd"] == pytest.approx(full["cost_ssd"] / 2)
    assert shrunk["efficiency_reduces_bill"] is True


def test_included_iops_are_three_per_provisioned_gb():
    """3 IOPS/GB までは込み。超過分だけが課金対象。"""
    r = calculate_fsxn_cost(1000, 512, iops=3000)
    assert r["included_iops"] == 1000 * SSD_INCLUDED_IOPS_PER_GB
    assert r["billed_extra_iops"] == 0
    assert r["cost_extra_iops"] == 0.0

    over = calculate_fsxn_cost(1000, 512, iops=4000)
    assert over["billed_extra_iops"] == 1000


# ---------------------------------------------------------------- 配置ごとの単価


def test_single_az_discount_is_not_uniform_across_dimensions():
    """**「Single-AZ は半額」は容量と IOPS にしか当てはまらない。**

    スループット容量は $0.906 対 $1.511 で 60.0% であり、半額ではない。リクエストは同額。
    一律の係数で Multi-AZ から Single-AZ を出すと、スループットの比重が大きい構成でずれる。
    """
    m = FSXN_RATES["MULTI_AZ_1"]
    s = FSXN_RATES["SINGLE_AZ_1"]
    for key in ("ssd", "capacity_pool", "ssd_iops"):
        assert s[key].api_price == pytest.approx(m[key].api_price / 2, rel=0.001), key
    ratio = s["throughput"].api_price / m["throughput"].api_price
    assert ratio == pytest.approx(0.600, abs=0.001)
    assert ratio > 0.5
    for key in ("pool_read", "pool_write"):
        assert s[key].api_price == m[key].api_price, key


def test_deployment_choice_changes_the_total():
    multi = calculate_fsxn_cost(1000, 512, deployment="MULTI_AZ_1")
    single = calculate_fsxn_cost(1000, 512, deployment="SINGLE_AZ_1")
    assert single["total_monthly_usd"] < multi["total_monthly_usd"]


def test_unknown_deployment_is_rejected():
    with pytest.raises(ValueError, match="unknown deployment"):
        calculate_fsxn_cost(1000, 512, deployment="MULTI_AZ_2")


# ---------------------------------------------------------------- EBS


def test_gp3_throughput_rate_is_converted_from_gibps_to_mibps():
    """**API は GiBps-mo で返す。** 換算を忘れると 1024 倍になる。"""
    assert EBS_RATES["gp3_throughput"].api_unit == "GiBps-mo"
    assert gp3_throughput_per_mbps() == pytest.approx(0.048, abs=1e-6)


def test_gp3_baseline_is_not_billed():
    r = calculate_ebs_gp3_cost(1000, iops=GP3_BASELINE_IOPS, throughput_mbps=125)
    assert r["cost_extra_iops"] == 0.0
    assert r["cost_extra_throughput"] == 0.0


def test_io2_iops_price_tiers_lower_the_marginal_rate():
    """**単価は階層で下がる。** 一律で最初の単価をかけると高 IOPS 側を過大に見積もる。"""
    flat = 100_000 * EBS_RATES["io2_iops_tier1"].api_price
    assert io2_iops_cost(100_000) < flat

    # 境界: 32,000 までは一律
    assert io2_iops_cost(IO2_TIER1_LIMIT) == pytest.approx(
        IO2_TIER1_LIMIT * EBS_RATES["io2_iops_tier1"].api_price
    )
    # 1 IOPS 超えたら 2 段目の単価が 1 IOPS 分だけ乗る
    step = io2_iops_cost(IO2_TIER1_LIMIT + 1) - io2_iops_cost(IO2_TIER1_LIMIT)
    assert step == pytest.approx(EBS_RATES["io2_iops_tier2"].api_price)
    # 3 段目も同様
    step3 = io2_iops_cost(IO2_TIER2_LIMIT + 1) - io2_iops_cost(IO2_TIER2_LIMIT)
    assert step3 == pytest.approx(EBS_RATES["io2_iops_tier3"].api_price)


def test_io2_total_includes_storage_and_tiered_iops():
    r = calculate_ebs_io2_cost(500, iops=40_000)
    expected = 500 * EBS_RATES["io2_storage"].api_price + io2_iops_cost(40_000)
    assert r["total_monthly_usd"] == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------- レポート


def test_report_states_that_it_is_not_a_production_estimate():
    report = generate_comparison_report(1000, 512, 0.65, 5000)
    assert "本番の見積りではありません" in report
    assert "効率化は既定では請求を下げません" in report


def test_report_lists_every_pinned_rate_with_its_usagetype():
    """**単価の出所を落とさない。** 額だけ出ていると照合できない。"""
    report = generate_comparison_report(1000, 512, 0.65, 5000, deployment="MULTI_AZ_1")
    for rate in FSXN_RATES["MULTI_AZ_1"].values():
        assert rate.usagetype in report, rate.usagetype
    for rate in EBS_RATES.values():
        assert rate.usagetype in report, rate.usagetype


def test_every_pinned_rate_carries_a_sku_and_usagetype():
    for deployment, rates in FSXN_RATES.items():
        for key, rate in rates.items():
            assert rate.sku, f"{deployment}/{key}"
            assert rate.usagetype.startswith("APN1-"), f"{deployment}/{key}"
    for key, rate in EBS_RATES.items():
        assert rate.sku, key
        assert rate.usagetype.startswith("APN1-"), key


# ---------------------------------------------------------------- 実現可能性

# **値段が付くことと出せることは別である。** 上限を超えた構成に金額だけを出すと、
# EBS 側に実現できない安い値が並び、比較そのものが成立しなくなる。


def test_gp3_throughput_is_capped_by_provisioned_iops():
    """**gp3 のスループットは確保 IOPS 1 につき 0.25 MiB/s まで。** 2,000 には 8,000 IOPS 必要。"""
    assert gp3_violations(8_000, 2_000) == []
    v = gp3_violations(5_000, 2_000)
    assert v and any("確保 IOPS" in x for x in v)


def test_gp3_per_volume_ceilings_are_flagged():
    assert any("上限 80,000" in x for x in gp3_violations(100_000, 500))
    assert any("2,000 MiB/s を超える" in x for x in gp3_violations(80_000, 4_096))
    assert gp3_violations(GP3_BASELINE_IOPS, 125) == []


def test_gp3_cost_still_returns_a_number_but_marks_it_infeasible():
    """金額は返す。ただし実現不能だと分かる形で返す。"""
    r = calculate_ebs_gp3_cost(1000, iops=5000, throughput_mbps=4096)
    assert r["total_monthly_usd"] > 0
    assert r["feasible"] is False
    assert r["violations"]


def test_io2_iops_ceiling_depends_on_the_instance_generation():
    """**256,000 は Nitro 世代のみ。** それ以外は 32,000 まで。"""
    assert io2_violations(200_000, nitro=True) == []
    assert io2_violations(200_000, nitro=False)
    assert calculate_ebs_io2_cost(500, iops=40_000, nitro=False)["feasible"] is False


def test_report_warns_when_the_ebs_column_cannot_be_delivered():
    report = generate_comparison_report(1000, 4096, 1.0, 5000)
    assert "この構成はボリューム 1 本では出せません" in report


# ---------------------------------------------------------------- 台数


def test_one_vm_is_the_least_favourable_shape_for_the_shared_file_system():
    """スループット容量はファイルシステムに 1 回、EBS はボリュームごとに買う。"""
    one = compare_at_scale(1, 100, 512, 5000)
    many = compare_at_scale(20, 100, 512, 5000)
    # FSx 側の 1 台あたり負担は下がる
    assert many["fsxn_monthly_usd"] / 20 < one["fsxn_monthly_usd"]


def test_scale_comparison_reports_feasibility_of_the_ebs_side():
    r = compare_at_scale(1, 100, 4096, 100_000)
    assert r["ebs_only_feasible"] is False
    assert r["ebs_only_violations"]


def test_crossover_returning_none_means_not_found_within_the_search_range():
    """**None は「存在しない」ではなく「探索範囲で見つからなかった」。**

    容量単価の差（$0.300 対 $0.096）が支配的な構成では台数を増やしても逆転しない。
    """
    assert find_crossover(100, 512, 5000, max_vms=50) is None


def test_vm_count_must_be_at_least_one():
    with pytest.raises(ValueError, match="1 以上"):
        compare_at_scale(0, 100, 512, 5000)
