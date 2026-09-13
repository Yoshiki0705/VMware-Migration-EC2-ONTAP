# Storage cost comparison — EBS only versus EBS + FSx for ONTAP

List-price monthly cost for placing the post-migration data volume on Amazon EBS versus
Amazon FSx for NetApp ONTAP.

> **This is a list-price calculation for a sample configuration, not a production estimate.**
> Unit prices were pulled from the AWS Price List API on 2026-09-13 (ap-northeast-1). Discounts,
> existing commitments, Savings Plans and EDP are not included.
> **Confirm with the AWS Pricing Calculator before deciding.**

## The conclusion first

**EBS is cheaper at small capacity and FSx for ONTAP is cheaper at large capacity.** The dividing
line is set almost entirely by throughput capacity: **14.0 TiB logical** at Multi-AZ with
512 MB/s, and **6.5 TiB logical** at Single-AZ with 512 MB/s.

| Scenario (logical capacity / 5,000 IOPS / 512 MB/s) | EBS only | EBS + FSx for ONTAP | Difference |
|---|---|---|---|
| 1,024 GB, no tiering (Multi-AZ) | $133.68 | $1,164.29 | +771% |
| 20,480 GB, 20% hot (Multi-AZ) | $2,001.46 | **$1,657.52** | **−17.2%** |
| 20,480 GB, 20% hot (Single-AZ) | $2,001.46 | **$908.21** | **−54.6%** |
| 51,200 GB, 20% hot (Multi-AZ) | $4,950.58 | **$2,976.14** | **−39.9%** |

Monthly USD, with the OS disk (EBS gp3 50 GB) included on both sides. **The EBS side is gp3.**
All types including gp2, io1, io2, st1 and sc1 are in [every volume type, side by side](#every-volume-type-side-by-side).
If durability is a requirement the comparator is io2 — read
[the availability assumptions](#the-availability-assumptions-do-not-match) first.

**Small configurations cost more because the 1,024 GiB SSD minimum and the throughput capacity
land as fixed cost.** As capacity grows, efficiency and tiering lower the per-logical-GB rate
until it crosses over.

## Every volume type, side by side

**Lining up only gp3 and io2 is not a comparison.** HDD costs an order of magnitude less per GB
than SSD, and **sc1 at $0.018/GB is cheaper than the FSx for ONTAP capacity pool at $0.0476/GB.**
That still does not settle the choice, because the performance shape differs.

Same requirement across all types (5,000 IOPS / 512 MB/s, 20% hot, 70% efficiency).

### Ranking at 2 TiB logical

| Configuration | Monthly | Per logical GB | Meets the requirement |
|---|---|---|---|
| Cold HDD sc1 | $36.86 | $0.0180 | **no** |
| Throughput Optimized HDD st1 | $110.59 | $0.0540 | **no** |
| General Purpose SSD gp3 | $214.90 | $0.1049 | yes |
| General Purpose SSD gp2 | $245.76 | $0.1200 | **no** |
| Provisioned IOPS SSD io1 | $660.82 | $0.3227 | yes |
| Provisioned IOPS SSD io2 | $660.82 | $0.3227 | yes |
| **FSx for ONTAP (Multi-AZ)** | **$796.07** | $0.3887 | yes |

### Ranking at 50 TiB logical

| Configuration | Monthly | Per logical GB | Meets the requirement |
|---|---|---|---|
| Cold HDD sc1 | $921.60 | $0.0180 | **no** |
| Throughput Optimized HDD st1 | $2,764.80 | $0.0540 | **no** |
| **FSx for ONTAP (Multi-AZ)** | **$2,971.34** | **$0.0580** | yes |
| General Purpose SSD gp3 | $4,945.78 | $0.0966 | yes |
| General Purpose SSD gp2 | $6,144.00 | $0.1200 | **no** |
| Provisioned IOPS SSD io1 | $7,640.40 | $0.1492 | yes |
| Provisioned IOPS SSD io2 | $7,640.40 | $0.1492 | yes |

**Among the options that meet the requirement, FSx is the most expensive at 2 TiB and the cheapest
at 50 TiB.** At 50 TiB it is $0.0580 per logical GB — **close to st1's $0.0540 and 0.60x gp3.**

**What disqualifies the others is a performance ceiling.**

- **sc1**: sustains 12 MiB/s per TiB. Even at 20 TiB that is 240 MB/s, short of 512 MB/s
- **st1**: sustains 40 MiB/s per TiB, capped at 500 MB/s. **500 MB/s needs 12.5 TiB or more**
- **st1 and sc1 both**: **cannot provision IOPS and cannot boot**
- **gp2**: throughput is capped at 250 MiB/s

### What is easy to miss per type

| Type | Condition |
|---|---|
| General Purpose SSD gp3 | **No burst.** Sustains provisioned performance indefinitely. IOPS at 500 per GiB, throughput at 0.25 MiB/s per provisioned IOPS (2,000 MiB/s requires 8,000 IOPS) |
| General Purpose SSD gp2 | **Performance tracks size** (3 IOPS/GiB, capped at 16,000). Volumes under 1 TiB burst to 3,000 IOPS. **25% more per GB than gp3** |
| Provisioned IOPS SSD io2 | **Two orders of magnitude more durable** (99.999%). IOPS price tiers down at 32,000 and 64,000. Block Express averages under 500 microseconds for 16 KiB I/O |
| Provisioned IOPS SSD io1 | **Same capacity price as io2, two orders of magnitude less durable, and its IOPS price does not tier.** No price-based reason to choose it new |
| Throughput Optimized HDD st1 | **No boot, unsuited to small random I/O.** Baseline 40 MiB/s per TiB |
| Cold HDD sc1 | **Cheapest per GB. Baseline is 12 MiB/s per TiB.** No boot |
| FSx for ONTAP | **Throughput capacity is bought once per file system.** 1,024 GiB minimum SSD. Sub-millisecond on SSD, tens of ms on the capacity pool |

Sources: [General Purpose SSD](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html),
[Provisioned IOPS SSD](https://docs.aws.amazon.com/ebs/latest/userguide/provisioned-iops.html),
[HDD](https://docs.aws.amazon.com/ebs/latest/userguide/hdd-vols.html).

**Whether HDD can serve the post-migration data volume depends on the I/O shape.** Large sequential
I/O makes it a candidate; for small random I/O, AWS itself recommends SSD.

## Effective rate per logical GB

**FSx for ONTAP provisions the SSD that the post-efficiency physical data fits into, not the
logical capacity.** Volumes are thin provisioned by default, and cold data is tiered to the
capacity pool. Lining logical capacity up 1:1 against EBS treats a reduction that exists only on
the FSx side as zero.

Capacity-only rate, computed at 100 TB logical so the minimum floor does not distort it:

| Share kept on SSD (hot) | Per logical GB | Against EBS gp3 |
|---|---|---|
| 100% (no tiering) | $0.1125 | FSx 1.17x more expensive |
| 50% | $0.0690 | FSx 1.39x cheaper |
| 20% | $0.0429 | **FSx 2.24x cheaper** |
| 10% | $0.0342 | FSx 2.80x cheaper |

Assumptions: 0.30 remaining after efficiency (70% reduction for VM workloads), 1 GiB of SSD
metadata per 10 GiB tiered, and SSD sized against the 80% utilization recommendation.

**Without tiering, the per-logical-GB rate exceeds EBS.** What produces the reversal is
efficiency and tiering together; neither alone does it.

## Where the crossover falls

| Throughput capacity | Multi-AZ | Single-AZ |
|---|---|---|
| 128 MB/s | 5.8 TiB | 2.9 TiB |
| 256 MB/s | 7.9 TiB | 4.1 TiB |
| 512 MB/s | 13.9 TiB | 6.5 TiB |
| 1,024 MB/s | 27.7 TiB | 11.6 TiB |
| 2,048 MB/s | 55.2 TiB | 23.1 TiB |
| 4,096 MB/s | 110.4 TiB | 46.1 TiB |

At 20% hot, 0.30 remaining after efficiency, IOPS within the 3 IOPS/GB allowance.

**The crossover is proportional to throughput capacity**, because that is where the fixed cost
sits. **Provisioning more throughput capacity than needed pushes the crossover out by the same
proportion.**

> **The throughput capacity you need cannot be derived by dividing required bandwidth.** In a
> sibling project's measurements, three environments running the same procedure, the same
> template and the same negotiated result spread 2.64x
> ([results](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/1bedd45/docs/ja/verification/perf-matrix-results.md#f-3-と再現性の実測)).
> **This series has not measured it.**

## How efficiency and tiering reach the bill

**They reach it by reducing what has to be provisioned, not by making provisioned capacity
cheaper.**

| Feature | Effect on the bill | Source |
|---|---|---|
| Compression, deduplication, compaction | Physical data shrinks, so less SSD needs provisioning. **70% reduction is the published figure for VMs** | [Managing storage capacity](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html) |
| Thin provisioning | Volumes are thin by default. **What is provisioned is the file system's SSD, not the sum of volume sizes** | [How to size](https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/) |
| Tiering (FabricPool) | Moves cold data to $0.0476/GB against $0.300/GB on SSD, a factor of 6.3 | [as above](https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/) |
| Snapshots | No separate charge; they consume provisioned SSD. **The saving comes from tiering and block sharing** | [as above](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html) |
| FlexClone | No copy at creation; only rewritten blocks add capacity | [Cloning](https://aws.amazon.com/blogs/storage/accelerate-development-refresh-cycles-and-optimize-cost-with-amazon-fsx-for-netapp-ontap-cloning) |

AWS's published reduction figures by workload (compression + deduplication):

| Workload | Compression only | Deduplication only | Both |
|---|---|---|---|
| **Virtual servers and desktops** | 55% | 70% | **70%** |
| General-purpose file shares | 50% | 30% | 65% |
| Databases | 65–70% | 0% | 65–70% |
| Engineering data | 55% | 30% | 75% |

**These are AWS's published typical figures, not measurements from this project.** Actual
reduction depends on the data.

## What clones change

**FlexClone does not copy data at creation.** On the EBS side each clone is an independent
volume restored from a snapshot, so every clone provisions the full capacity.

2,048 GB in production, 10% rewritten per clone, 512 MB/s, no tiering:

| Clones | EBS billed | EBS monthly | FSx billed | FSx monthly |
|---|---|---|---|---|
| 0 | 2,048 GB | $215.18 | 2,048 GB | $1,080.83 |
| 3 | 8,192 GB | $860.72 | 2,662 GB | $1,080.83 |
| **5** | 12,288 GB | $1,291.08 | 3,072 GB | **$1,119.23** |
| 10 | 22,528 GB | $2,366.98 | 4,096 GB | $1,234.43 |

**On these assumptions it crosses over at five clones.** The delta ratio has to be measured;
**the 10% default has nothing behind it.** How much a development clone is rewritten depends on
the workload.

## Three values that decide the answer

**The conclusion turns on these three, and none of the defaults has evidence behind it.**

| Value | What it moves | How to determine it |
|---|---|---|
| Hot/cold ratio | The per-logical-GB rate, which moves 2.6x between 100% and 20% | AWS suggests analysing access logs and last-access times, asking application owners, and observing a pilot |
| Remaining ratio after efficiency | Directly changes the SSD to provision | Measure on real data; published figures are typical values |
| Throughput capacity | Proportional to the crossover; most of the fixed cost | Measure. **Division does not settle it** |

## Constraints, and asymmetries that affect cost

### First-generation file systems cannot decrease SSD

**`MULTI_AZ_1` and `SINGLE_AZ_1` cannot reduce SSD capacity after the fact.** Decrease is
second-generation only, in steps of at least 9%, and utilization must stay under 80% afterwards
([source](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/storage-capacity-and-IOPS.html)).

**So realising the efficiency saving means provisioning less from the start.** Over-provisioning
and trimming later does not work on first-generation. There is also a six-hour cooldown between
capacity and throughput changes.

### The availability assumptions do not match

**The tables above line up configurations whose availability commitments differ.** Putting the SLAs
side by side makes the gap numeric.

| Configuration | SLA (monthly uptime) | Unit it applies to | Allowed downtime per month | Designed durability |
|---|---|---|---|---|
| FSx for ONTAP Multi-AZ | **99.99%** | One file system (active-standby across 2 AZs) | ~4.3 min | not published |
| FSx for ONTAP Single-AZ | **99.9%** | One file system (active-standby in 1 AZ) | ~43.2 min | not published |
| A single EBS volume (**gp3 or io2**) | **99.9%** | One volume (Volume-Level SLA) | ~43.2 min | gp3: 99.8–99.9% (AFR 0.1–0.2%)<br>**io2: 99.999% (0.001%)** |
| EBS across 2 or more AZs | **99.99%** | All volumes across 2+ AZs (Region-Level SLA) | ~4.3 min | as above |

Sources: [Amazon FSx SLA](https://aws.amazon.com/fsx/sla/) (2024-06-25),
[Amazon EBS SLA](https://aws.amazon.com/ebs/sla/) (2022-05-31),
[EBS volume types](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volume-types.html).
Allowed downtime is derived from a 30-day month (43,200 minutes) for reference.

**Three things follow.**

**1. The EBS SLA does not differ by volume type.** gp3 and io2 both carry a 99.9% Volume-Level
commitment. **What differs is durability**, where io2's 99.999% is two orders of magnitude above
gp3's 99.8–99.9%. **If durability is a requirement, the comparator is io2 (configuration C), not
gp3 (configuration A).** Configuration C is labelled "high IOPS" in the cost tables above, but
**it is also the durability-matched comparator.**

**2. Reaching 99.99% on the EBS side requires volumes in two or more AZs.** The Region-Level SLA
applies to all volumes across 2+ AZs, so **a single volume cannot qualify.** That takes
application-level replication, whose cost and operation are not in the tables above. Multi-AZ FSx
for ONTAP carries **99.99% for one file system.**

**3. FSx for ONTAP publishes no durability percentage.** There is no figure to place against io2's
99.999%, so **published figures cannot settle which is more durable.** The SLAs are comparable; on
durability, what can be said stops at "io2 is 99.999%, FSx for ONTAP is not published".

**An SLA is a commitment, not a record.** The remedy for falling short is a service credit, not a
guarantee of availability (see also the exclusions in the
[FSx](https://aws.amazon.com/fsx/sla/) and [EBS](https://aws.amazon.com/ebs/sla/) SLAs).

### Tiering trades latency

Capacity pool latency is tens of milliseconds against sub-millisecond on SSD. **Lowering the hot
ratio lowers the rate, but reads of tiered data get slower and request charges apply** (read
$0.00037/1,000, write $0.0047/1,000 — **writes are 12.7x**).

### Boot volumes stay on EBS

**EC2 cannot boot from FSx for ONTAP.** The OS disk is EBS in both configurations, so it does not
appear in the difference, but it remains in the total.

### The free EBS baseline, and its per-volume ceilings

**Each EBS volume includes 3,000 IOPS and 125 MB/s at no additional charge.** Splitting the same
aggregate across more volumes multiplies that allowance and lowers the EBS bill. A single volume
does have ceilings, however.

| Constraint | Value | Source |
|---|---|---|
| gp3 IOPS | 3,000–80,000 | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |
| gp3 throughput | 125–2,000 MiB/s | [General Purpose SSD](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html) |
| gp3 throughput against IOPS | **0.25 MiB/s per provisioned IOPS** (2,000 MiB/s requires 8,000 IOPS) | as above |
| io2 IOPS | 100–256,000 (**256,000 on Nitro instances only; 32,000 otherwise**) | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |

`scripts/cost_comparison.py` detects configurations that violate these and **prints the cost
while marking it undeliverable.**

## What this comparison excludes

- **EC2 instance cost**: assumed identical in count and type, so it does not appear in the
  difference
- **Backups**: FSx for ONTAP backups are billed on consumption. **A final backup is taken by
  default when a volume is deleted, and it keeps billing if left behind**
  ([teardown](quickstart.md#delete-stack))
- **EBS snapshot storage**: stored in S3 and billed by size
- **Data transfer**: across AZs and Regions. Multi-AZ replication between nodes is included in
  the throughput capacity charge
- **Migration tooling**: the cost of AWS Transform or Shift Toolkit, and the period during which
  capacity is held on both sides
- **Licensing**: OS and application license mobility terms

## Reproducing this

```bash
# Defaults (Multi-AZ, VM workload at 70% reduction, no tiering)
python3 scripts/cost_comparison.py --data-size 20480

# Tiered at 20% hot, Single-AZ
python3 scripts/cost_comparison.py --data-size 20480 --hot-ratio 0.2 --deployment SINGLE_AZ_1

# With five clones
python3 scripts/cost_comparison.py --data-size 2048 --clone-count 5 --clone-delta-ratio 0.10

# Switch the efficiency assumption by workload
python3 scripts/cost_comparison.py --workload database --data-size 20480

# Reconcile the pinned rates against the Price List API (requires AWS credentials)
python3 scripts/cost_comparison.py --check-prices
```

**All 19 rates carry a SKU and a usagetype.** `--check-prices` compares each against the API's
`pricePerUnit`, prints the item name and both values on any mismatch, and exits 1.

## Related documents

| Document | Contents |
|---|---|
| [Migration method comparison](migration-method-comparison.md) | Which tool to migrate with |
| [Quickstart](quickstart.md) | Building and tearing down the environment |
| [iSCSI setup](fsxn-iscsi-setup.md) | Creating and mounting the LUN |
