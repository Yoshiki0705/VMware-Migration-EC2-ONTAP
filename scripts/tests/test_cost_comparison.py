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
    EFFICIENCY_BY_WORKLOAD,
    FSXN_RATES,
    GP3_BASELINE_IOPS,
    IO2_TIER1_LIMIT,
    IO2_TIER2_LIMIT,
    MIN_SSD_GIB,
    SERVICE_LEVELS,
    SNAPSHOT_RATES,
    SSD_DECREASE_SUPPORTED,
    SSD_INCLUDED_IOPS_PER_GB,
    SSD_UTILIZATION_TARGET,
    TIERING_POLICIES,
    TRANSFER_DIRECTIONS_PER_REPLICATED_GB,
    TRANSFER_RATES,
    VOLUME_SPECS,
    calculate_ebs_cost,
    calculate_ebs_gp3_cost,
    calculate_ebs_io2_cost,
    calculate_fsxn_cost,
    compare_all_volume_types,
    compare_at_scale,
    compare_with_clones,
    ebs_multi_az_cost,
    find_capacity_crossover,
    find_crossover,
    fsxn_cross_az_access_cost,
    generate_comparison_report,
    gp3_throughput_per_mbps,
    gp3_violations,
    hdd_throughput,
    io2_iops_cost,
    io2_violations,
    single_az_transfer_breakeven_gb,
    size_fsxn_capacity,
    tiering_effective,
)

# ---------------------------------------------------------------- リクエスト課金


def test_request_cost_uses_per_operation_rate_not_per_million():
    """**1 オペレーションあたりの単価に百万を掛ける。**

    以前は「百万リクエストあたり $0.0055」という値を持っており、実際の単価
    （読み $0.00037 / 1,000 = 1 オペレーション $0.00000037）と 3 桁ずれていた。
    """
    r = calculate_fsxn_cost(100, 128, hot_ratio=0.0, pool_read_requests_millions=1.0)
    rate = FSXN_RATES["MULTI_AZ_1"]["pool_read"].api_price
    assert r["cost_pool_read_requests"] == pytest.approx(1_000_000 * rate, abs=0.01)
    # 100 万回の読みで $0.37。桁を取り違えていないことを額でも固定する
    assert r["cost_pool_read_requests"] == pytest.approx(0.37, abs=0.01)


def test_write_requests_cost_more_than_reads():
    """**書きは読みより高い。** 単一の混合単価にまとめると、書きが多い経路を過小に見積もる。"""
    reads = calculate_fsxn_cost(100, 128, hot_ratio=0.0, pool_read_requests_millions=10.0)
    writes = calculate_fsxn_cost(100, 128, hot_ratio=0.0, pool_write_requests_millions=10.0)
    assert writes["cost_pool_write_requests"] > reads["cost_pool_read_requests"]
    ratio = writes["cost_pool_write_requests"] / reads["cost_pool_read_requests"]
    assert ratio == pytest.approx(0.0047 / 0.00037, rel=0.01)


# ---------------------------------------------------------------- サイジング

# **効率化と階層化を確保量に反映させないと比較が成立しない。** EBS は論理容量をそのまま確保するが、
# FSx for ONTAP が確保するのは「効率化後の物理データが収まる SSD」である。


def test_efficiency_lowers_the_provisioned_ssd_requirement():
    """効率化は確保量を減らす。**それが請求に効く経路である。**"""
    none = size_fsxn_capacity(100_000, efficiency_ratio=1.0)
    vm = size_fsxn_capacity(100_000, efficiency_ratio=EFFICIENCY_BY_WORKLOAD["vm"])
    assert vm["physical_gb"] == pytest.approx(30_000)
    assert vm["ssd_needed_gb"] < none["ssd_needed_gb"]


def test_aws_published_efficiency_for_vm_workloads_is_seventy_percent():
    """**AWS の公表代表値で、このプロジェクトの実測値ではない。**"""
    assert EFFICIENCY_BY_WORKLOAD["vm"] == 0.30
    assert EFFICIENCY_BY_WORKLOAD["file-share"] == 0.35
    assert EFFICIENCY_BY_WORKLOAD["none"] == 1.00


def test_tiering_leaves_metadata_on_ssd():
    """**階層化しても SSD がゼロにはならない。** 容量プール 10 GiB につき 1 GiB が残る。"""
    s = size_fsxn_capacity(100_000, efficiency_ratio=1.0, hot_ratio=0.0)
    assert s["capacity_pool_gb"] == pytest.approx(100_000)
    assert s["pool_metadata_gb"] == pytest.approx(10_000)
    assert s["ssd_needed_gb"] == pytest.approx(10_000 / SSD_UTILIZATION_TARGET)


def test_ssd_is_sized_to_the_eighty_percent_utilization_recommendation():
    s = size_fsxn_capacity(100_000, efficiency_ratio=1.0, hot_ratio=1.0)
    assert s["ssd_needed_gb"] == pytest.approx(100_000 / SSD_UTILIZATION_TARGET)


def test_minimum_ssd_floor_dominates_small_configurations():
    """**小さい構成では 1,024 GiB の床が支配する。** ここが FSx が高く出る理由である。"""
    s = size_fsxn_capacity(500, efficiency_ratio=EFFICIENCY_BY_WORKLOAD["vm"], hot_ratio=0.2)
    assert s["at_minimum_floor"] is True
    assert s["provisioned_ssd_gb"] == MIN_SSD_GIB

    big = size_fsxn_capacity(100_000, efficiency_ratio=EFFICIENCY_BY_WORKLOAD["vm"], hot_ratio=0.2)
    assert big["at_minimum_floor"] is False


def test_first_generation_cannot_decrease_ssd():
    """**第一世代は SSD を減らせない。** 効率化を請求に反映させるには最初から少なく確保する。"""
    for deployment in ("MULTI_AZ_1", "SINGLE_AZ_1"):
        assert SSD_DECREASE_SUPPORTED[deployment] is False
        assert (
            calculate_fsxn_cost(1000, 512, deployment=deployment)["ssd_decrease_supported"] is False
        )


def test_sizing_rejects_out_of_range_inputs():
    with pytest.raises(ValueError, match="efficiency_ratio"):
        size_fsxn_capacity(1000, efficiency_ratio=0.0)
    with pytest.raises(ValueError, match="hot_ratio"):
        size_fsxn_capacity(1000, hot_ratio=1.5)


# ---------------------------------------------------------------- 逆転点


def test_fsxn_is_more_expensive_below_the_crossover_and_cheaper_above():
    """**小さい構成では EBS、大きい構成では FSx。** 片方だけを示すと結論が反転する。"""
    small = calculate_fsxn_cost(1024, 512, hot_ratio=0.2, iops=5000)
    small_ebs = calculate_ebs_gp3_cost(1024, iops=5000, throughput_mbps=512)
    assert small["total_monthly_usd"] > small_ebs["total_monthly_usd"]

    big = calculate_fsxn_cost(51_200, 512, hot_ratio=0.2, iops=5000)
    big_ebs = calculate_ebs_gp3_cost(51_200, iops=5000, throughput_mbps=512)
    assert big["total_monthly_usd"] < big_ebs["total_monthly_usd"]


def test_crossover_moves_with_throughput_capacity():
    """**逆転点はスループット容量でほぼ決まる。** 固定費がそこに集中している。"""
    low = find_capacity_crossover(128, hot_ratio=0.20)
    high = find_capacity_crossover(2048, hot_ratio=0.20)
    assert low is not None and high is not None
    assert high > low * 5


def test_single_az_crosses_over_earlier_than_multi_az():
    m = find_capacity_crossover(512, deployment="MULTI_AZ_1", hot_ratio=0.20)
    s = find_capacity_crossover(512, deployment="SINGLE_AZ_1", hot_ratio=0.20)
    assert s < m


def test_without_tiering_the_per_logical_gb_rate_can_exceed_gp3():
    """**階層化しないと 1 論理 GB あたりで EBS を上回りうる。** 階層化が効いている分を示す。"""
    hot_only = calculate_fsxn_cost(100_000, 128, hot_ratio=1.0)
    tiered = calculate_fsxn_cost(100_000, 128, hot_ratio=0.20)
    assert hot_only["usd_per_logical_gb"] > tiered["usd_per_logical_gb"]


# ---------------------------------------------------------------- 複製


def test_clones_shift_the_comparison_because_flexclone_shares_blocks():
    """**FlexClone は作成時にコピーしない。** EBS 側は複製ごとに全容量を確保する。"""
    none = compare_with_clones(2048, 0, 0.10, 512)
    many = compare_with_clones(2048, 10, 0.10, 512)
    assert many["ebs_billed_logical_gb"] == pytest.approx(2048 * 11)
    # FSx 側は差分だけ
    assert many["fsxn_billed_logical_gb"] == pytest.approx(2048 * (1 + 10 * 0.10))
    assert none["fsxn_is_cheaper"] is False
    assert many["fsxn_is_cheaper"] is True


def test_clone_inputs_are_validated():
    with pytest.raises(ValueError, match="clone_count"):
        compare_with_clones(1000, -1, 0.1, 512)
    with pytest.raises(ValueError, match="clone_delta_ratio"):
        compare_with_clones(1000, 1, 1.5, 512)


def test_included_iops_are_three_per_provisioned_gb():
    """3 IOPS/GB までは込み。超過分だけが課金対象。確保 SSD に対して計算される。"""
    r = calculate_fsxn_cost(1000, 512, efficiency_ratio=1.0, iops=3000)
    assert r["included_iops"] == r["provisioned_ssd_gb"] * SSD_INCLUDED_IOPS_PER_GB
    assert r["billed_extra_iops"] == 0
    assert r["cost_extra_iops"] == 0.0

    over = calculate_fsxn_cost(1000, 512, efficiency_ratio=1.0, iops=99_999)
    assert over["billed_extra_iops"] > 0


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
    assert "確保量を減らすことで請求に効きます" in report
    assert "実測値ではありません" in report


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


def test_report_states_when_the_minimum_ssd_floor_dominates():
    report = generate_comparison_report(500, 128, 0.30, 0, hot_ratio=0.2)
    assert "床が支配しています" in report


def test_report_states_the_capacity_crossover():
    report = generate_comparison_report(1024, 512, 0.30, 5000, hot_ratio=0.2)
    assert "を超えると" in report


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


# ---------------------------------------------------------------- SLA と耐久性

# **費用の比較は可用性の前提を揃えないと成立しない。** ここで固定するのは、公表されている
# コミットメントの構造で、額ではない。


def test_ebs_sla_does_not_differ_by_volume_type():
    """**EBS の SLA はボリュームタイプで分かれない。** 分かれるのは耐久性である。

    gp3 と io2 はどちらも Volume-Level 99.9%。この 1 本の SLA が両タイプに当たるので、
    「io2 は SLA が高い」は誤り。io2 が高いのは耐久性（99.999% 対 99.8〜99.9%）。
    """
    ebs = SERVICE_LEVELS["ebs_volume"]
    assert ebs.sla_uptime == "99.9%"
    assert "gp3" in ebs.durability and "io2" in ebs.durability
    assert "99.999%" in ebs.durability


def test_multi_az_fsxn_commits_to_four_nines_on_a_single_file_system():
    """**Multi-AZ の FSx for ONTAP は 99.99%。** 単一のファイルシステムに対して。"""
    fsxn = SERVICE_LEVELS["fsxn_multi_az"]
    assert fsxn.sla_uptime == "99.99%"
    assert "ファイルシステム 1 つ" in fsxn.sla_scope


def test_ebs_needs_two_azs_for_the_same_four_nines():
    """**EBS の 99.99% は 2 AZ 以上の配置が条件。** 単一ボリュームでは満たせない。"""
    region = SERVICE_LEVELS["ebs_region"]
    volume = SERVICE_LEVELS["ebs_volume"]
    assert region.sla_uptime == "99.99%"
    assert volume.sla_uptime == "99.9%"
    assert "2 つ以上の AZ" in region.sla_scope
    assert "単一ボリュームでは満たせず" in region.sla_scope


def test_single_az_fsxn_matches_the_ebs_volume_commitment():
    """Single-AZ の FSx for ONTAP と EBS ボリューム 1 本は、どちらも 99.9%。"""
    assert SERVICE_LEVELS["fsxn_single_az"].sla_uptime == "99.9%"
    assert SERVICE_LEVELS["ebs_volume"].sla_uptime == "99.9%"


def test_fsxn_durability_is_not_published():
    """**FSx for ONTAP に耐久性のパーセンテージは公表されていない。**

    io2 の 99.999% と並べられる数値が無いので、耐久性の優劣は公表値から判定できない。
    ここを None のままにしておくことで、レポートが数値を作り出さないようにする。
    """
    assert SERVICE_LEVELS["fsxn_multi_az"].durability is None
    assert SERVICE_LEVELS["fsxn_single_az"].durability is None


def test_every_service_level_carries_a_source():
    for key, s in SERVICE_LEVELS.items():
        assert s.source.startswith("https://"), key
        assert s.sla_uptime.endswith("%"), key


def test_report_lists_the_sla_of_each_configuration():
    report = generate_comparison_report(20480, 512, 0.30, 5000, hot_ratio=0.2)
    assert "## SLA と耐久性" in report
    for key in SERVICE_LEVELS:
        assert SERVICE_LEVELS[key].sla_uptime in report
    assert "EBS の SLA はボリュームタイプで分かれません" in report
    assert "公表値からは耐久性の優劣を判定できません" in report


def test_report_names_io2_as_the_durability_matched_comparator():
    """**構成 C は高 IOPS 向けだけでなく、耐久性を揃えた比較対象でもある。**"""
    report = generate_comparison_report(20480, 512, 0.30, 5000, hot_ratio=0.2)
    assert "耐久性を揃えて比べるなら比較対象は io2" in report
    assert "耐久性を揃えた比較対象" in report


# ---------------------------------------------------------------- 全ボリュームタイプ

# **2 タイプだけ並べると比較にならない。** HDD の GB 単価は SSD より 1 桁安く、sc1 は FSx の
# 容量プールより安い。安さが選定の答えにならないのは、性能の形が違うからである。


def test_every_ebs_type_has_a_price_and_a_spec():
    for vt in ("gp3", "gp2", "io1", "io2", "st1", "sc1"):
        assert vt in VOLUME_SPECS, vt
        r = calculate_ebs_cost(vt, 1000, iops=0, throughput_mbps=0)
        assert r["total_monthly_usd"] > 0, vt


def test_sc1_is_cheaper_per_gb_than_the_fsxn_capacity_pool():
    """**最安の EBS は FSx の容量プールより安い。** それでも要件を満たすかは別問題。"""
    sc1 = EBS_RATES["sc1_storage"].api_price
    pool = FSXN_RATES["MULTI_AZ_1"]["capacity_pool"].api_price
    assert sc1 < pool
    # ただし継続スループットはサイズ依存で、1 TiB では 12 MiB/s しか出ない
    assert hdd_throughput("sc1", 1024)["sustained_mbps"] == pytest.approx(12.0)


def test_hdd_throughput_scales_with_size_and_caps():
    """**「st1 は 500 MiB/s」は 12.5 TiB 以上での値。** 小さいボリュームでは出ない。"""
    assert hdd_throughput("st1", 1024)["sustained_mbps"] == pytest.approx(40.0)
    assert hdd_throughput("st1", int(12.5 * 1024))["sustained_mbps"] == pytest.approx(500.0)
    # 上限で止まる
    assert hdd_throughput("st1", 20 * 1024)["sustained_mbps"] == pytest.approx(500.0)
    # バーストとベースラインは別
    one_tib = hdd_throughput("st1", 1024)
    assert one_tib["burst_mbps"] > one_tib["sustained_mbps"]


def test_hdd_is_rejected_when_iops_are_required():
    """**HDD は IOPS を確保できない。** 要求されたら満たせないと返す。"""
    for vt in ("st1", "sc1"):
        r = calculate_ebs_cost(vt, 20480, iops=5000, throughput_mbps=100)
        assert r["feasible"] is False
        assert any("IOPS を確保できない" in v for v in r["violations"])


def test_hdd_cannot_boot():
    for vt in ("st1", "sc1"):
        assert VOLUME_SPECS[vt].bootable is False
        assert VOLUME_SPECS[vt].random_io_suitable is False
    for vt in ("gp3", "gp2", "io1", "io2"):
        assert VOLUME_SPECS[vt].bootable is True


def test_gp2_iops_cannot_be_provisioned_and_track_size():
    """**gp2 は IOPS を指定できない。** 3 IOPS/GiB で決まる。"""
    r = calculate_ebs_cost("gp2", 100, iops=5000)
    assert r["feasible"] is False
    assert any("gp2 は IOPS を指定できない" in v for v in r["violations"])
    # 十分大きければ満たせる
    assert calculate_ebs_cost("gp2", 5000, iops=5000)["feasible"] is True


def test_gp2_costs_twenty_percent_more_per_gb_than_gp3():
    gp2 = EBS_RATES["gp2_storage"].api_price
    gp3 = EBS_RATES["gp3_storage"].api_price
    assert gp2 / gp3 == pytest.approx(1.25, rel=0.01)


def test_io1_and_io2_share_capacity_price_but_not_durability_or_iops_tiering():
    """**io1 は io2 と容量単価が同じで、耐久性が 2 桁低く、IOPS 単価は下がらない。**"""
    assert EBS_RATES["io1_storage"].api_price == EBS_RATES["io2_storage"].api_price
    assert EBS_RATES["io1_iops"].api_price == EBS_RATES["io2_iops_tier1"].api_price
    assert "99.999%" in VOLUME_SPECS["io2"].durability
    assert "99.999%" not in VOLUME_SPECS["io1"].durability
    # 高 IOPS では io2 のほうが安くなる
    high = 100_000
    io1 = calculate_ebs_cost("io1", 1000, iops=high)
    io2 = calculate_ebs_cost("io2", 1000, iops=high)
    assert io2["total_monthly_usd"] < io1["total_monthly_usd"]


def test_comparison_includes_every_type_and_fsxn():
    rows = compare_all_volume_types(20480, 5000, 512, hot_ratio=0.2)
    assert len(rows) == len(VOLUME_SPECS) + 1
    assert sum(1 for r in rows if r["kind"] == "FSx") == 1


def test_cheapest_row_can_be_the_one_that_does_not_meet_the_requirement():
    """**額だけで選べない。** 一番安い行が要件を満たさないことがある。"""
    rows = sorted(
        compare_all_volume_types(20480, 5000, 512, hot_ratio=0.2), key=lambda r: r["monthly_usd"]
    )
    assert rows[0]["feasible"] is False
    # 要件を満たすものの中で最安を取ると FSx になる（この条件では）
    feasible = [r for r in rows if r["feasible"]]
    assert feasible[0]["kind"] == "FSx"


def test_unknown_volume_type_is_rejected():
    with pytest.raises(ValueError, match="unknown volume type"):
        calculate_ebs_cost("gp4", 1000)


def test_report_lists_all_volume_types_with_their_constraints():
    report = generate_comparison_report(20480, 512, 0.30, 5000, hot_ratio=0.2)
    assert "## 全ボリュームタイプとの横並び" in report
    for spec in VOLUME_SPECS.values():
        assert spec.label in report, spec.label
    assert "額だけで選べません" in report


# ---------------------------------------------------------------- AZ をまたぐ費用

# **可用性を揃えないと費用の比較が成立しない。** EBS の 99.99% は 2 AZ 以上に「アタッチされた」
# ボリュームが条件で、複製は自分で作る。FSx の Multi-AZ は AZ 間複製が料金に含まれる。


def test_two_az_ebs_doubles_the_volume_cost_and_adds_transfer():
    one = calculate_ebs_cost("gp3", 20480, iops=5000, throughput_mbps=512)
    two = ebs_multi_az_cost("gp3", 20480, 5120, iops=5000, throughput_mbps=512)
    assert two["two_az_volumes_monthly_usd"] == pytest.approx(one["total_monthly_usd"] * 2)
    assert two["cross_az_transfer_monthly_usd"] > 0
    assert two["total_monthly_usd"] > one["total_monthly_usd"] * 2


def test_cross_az_transfer_is_charged_in_both_directions():
    """**AWS は「$0.01/GB in each direction」と書いている。** 片方向 1 GB は $0.02。"""
    assert TRANSFER_DIRECTIONS_PER_REPLICATED_GB == 2
    r = ebs_multi_az_cost("gp3", 1000, 1000)
    expected = 1000 * TRANSFER_RATES["intra_region"].api_price * 2
    assert r["cross_az_transfer_monthly_usd"] == pytest.approx(expected)
    assert r["cross_az_transfer_monthly_usd"] == pytest.approx(20.0)


def test_snapshots_do_not_satisfy_the_region_level_sla():
    """**スナップショットは代替にならない。** 条件は「アタッチされたボリューム」である。"""
    r = ebs_multi_az_cost("gp3", 20480, 5120)
    assert r["snapshot_meets_region_sla"] is False
    assert r["snapshot_only_alternative_usd"] > 0


def test_two_az_cost_records_what_it_does_not_count():
    """**数えていないものを列挙する。** 待機インスタンスと運用は入っていない。"""
    r = ebs_multi_az_cost("gp3", 20480, 5120)
    assert len(r["not_counted"]) >= 3
    assert any("EC2" in x for x in r["not_counted"])


def test_multi_az_fsxn_has_no_cross_az_transfer_charge():
    """**Multi-AZ の AZ 間複製はスループット容量の料金に含まれる。**"""
    r = fsxn_cross_az_access_cost("MULTI_AZ_1", 100_000)
    assert r["cross_az_transfer_monthly_usd"] == 0.0
    assert r["replication_included_in_throughput"] is True


def test_single_az_fsxn_is_charged_for_cross_az_access():
    """**Single-AZ は各方向 $0.01/GB。** 容量単価で浮いた分が戻ってくる経路である。"""
    r = fsxn_cross_az_access_cost("SINGLE_AZ_1", 10_000)
    assert r["cross_az_transfer_monthly_usd"] == pytest.approx(10_000 * 0.01 * 2)
    assert r["replication_included_in_throughput"] is False


def test_single_az_has_a_transfer_breakeven_against_multi_az():
    """**AZ をまたぐ量がこの値を超えると Single-AZ のほうが高くなる。**"""
    be = single_az_transfer_breakeven_gb(20480, 512, hot_ratio=0.2, iops=5000)
    assert be is not None and be > 0
    # 境界の前後で順位が入れ替わる
    single = calculate_fsxn_cost(20480, 512, deployment="SINGLE_AZ_1", hot_ratio=0.2, iops=5000)[
        "total_monthly_usd"
    ]
    multi = calculate_fsxn_cost(20480, 512, deployment="MULTI_AZ_1", hot_ratio=0.2, iops=5000)[
        "total_monthly_usd"
    ]
    below = (
        single + fsxn_cross_az_access_cost("SINGLE_AZ_1", be * 0.5)["cross_az_transfer_monthly_usd"]
    )
    above = (
        single + fsxn_cross_az_access_cost("SINGLE_AZ_1", be * 1.5)["cross_az_transfer_monthly_usd"]
    )
    assert below < multi < above


def test_fsxn_multi_az_beats_two_az_ebs_at_matched_availability():
    """この条件では、99.99% を揃えると FSx のほうが安い。**条件つきの結論である。**"""
    ebs = ebs_multi_az_cost("gp3", 20480, 5120, iops=5000, throughput_mbps=512)
    fsxn = calculate_fsxn_cost(20480, 512, hot_ratio=0.2, iops=5000)
    assert fsxn["total_monthly_usd"] < ebs["total_monthly_usd"]


def test_report_compares_at_matched_availability():
    report = generate_comparison_report(20480, 512, 0.30, 5000, hot_ratio=0.2)
    assert "## 可用性を揃えた比較（99.99%）" in report
    assert "スナップショットは代替になりません" in report
    assert "Multi-Attach も代替になりません" in report
    assert "数えていない費用があります" in report


def test_transfer_and_snapshot_rates_carry_provenance():
    for name, table in (("transfer", TRANSFER_RATES), ("snapshot", SNAPSHOT_RATES)):
        for key, rate in table.items():
            assert rate.sku, f"{name}/{key}"
            assert rate.usagetype, f"{name}/{key}"


# ---------------------------------------------------------------- 階層化の成立条件

# **階層化は「設定すれば効く」レバーではない。** ブロックでこれを読み違えると、
# 逆転点そのものが消える。ここで固定するのは、その条件である。


def test_default_tiering_policy_differs_by_creation_path():
    """**コンソールは auto、CLI / API / ONTAP CLI は snapshot-only。**

    IaC と ONTAP CLI で作るブロック構成は既定が snapshot-only になる。
    """
    assert "コンソール" in TIERING_POLICIES["auto"].default_for
    assert "CLI" in TIERING_POLICIES["snapshot-only"].default_for
    assert TIERING_POLICIES["auto"].tiers_active_data is True
    assert TIERING_POLICIES["snapshot-only"].tiers_active_data is False


def test_snapshot_only_ignores_the_hot_ratio():
    """**アクティブなデータを階層化しないポリシーでは hot 比率が成立しない。**"""
    s = size_fsxn_capacity(20480, 0.30, hot_ratio=0.2, tiering_policy="snapshot-only")
    assert s["requested_hot_ratio"] == 0.2
    assert s["effective_hot_ratio"] == 1.0
    assert s["capacity_pool_gb"] == 0
    assert any("階層化しない" in n for n in s["policy_notes"])


def test_tiering_does_not_happen_below_fifty_percent_utilization():
    """**余裕を持って確保すると階層化が起きず、全量が SSD 単価で課金される。**"""
    assert tiering_effective("auto", 0.80)["tiers_active_data"] is True
    assert tiering_effective("auto", 0.50)["tiers_active_data"] is False
    assert tiering_effective("auto", 0.30)["tiers_active_data"] is False
    # all だけは 50% 以下でも階層化する
    assert tiering_effective("all", 0.30)["tiers_active_data"] is True


def test_high_utilization_stops_promotion_and_then_writes():
    at_90 = tiering_effective("auto", 0.90)
    assert any("SSD に戻りません" in r for r in at_90["reasons"])
    at_98 = tiering_effective("auto", 0.98)
    assert any("書き込めなくなります" in r for r in at_98["reasons"])


def test_auto_promotes_cold_blocks_on_random_read():
    """**LUN 上のファイルシステムはランダム読みを行う。** hot 比率は設計値では決まらない。"""
    assert TIERING_POLICIES["auto"].promotes_on_random_read is True
    assert TIERING_POLICIES["all"].promotes_on_random_read is False


def test_block_assumption_removes_the_crossover():
    """**階層化しない前提では逆転点が存在しない。** ブロックでの結論である。"""
    with_tiering = find_capacity_crossover(512, hot_ratio=0.20)
    without = find_capacity_crossover(512, hot_ratio=1.0)
    assert with_tiering is not None
    assert without is None


def test_snapshot_only_is_more_expensive_than_gp3_at_every_size_tested():
    for logical in (2048, 20480, 51200, 204800):
        f = calculate_fsxn_cost(
            logical, 512, hot_ratio=0.2, iops=5000, tiering_policy="snapshot-only"
        )
        e = calculate_ebs_cost("gp3", logical, iops=5000, throughput_mbps=512)
        assert f["total_monthly_usd"] > e["total_monthly_usd"], logical


def test_unknown_tiering_policy_is_rejected():
    with pytest.raises(ValueError, match="unknown tiering policy"):
        tiering_effective("sometimes", 0.8)


def test_report_warns_against_assuming_tiering_for_block():
    report = generate_comparison_report(20480, 512, 0.30, 5000, hot_ratio=0.2)
    assert "## ブロックストレージで階層化を前提にしないこと" in report
    assert "snapshot-only" in report
    assert "space-allocation" in report
    assert "実測値ではありません" in report
