# Storage cost comparison — EBS only versus EBS + FSx for ONTAP

List-price monthly cost for placing the post-migration data volume on Amazon EBS versus
Amazon FSx for NetApp ONTAP.

> **This is a list-price calculation for a sample configuration, not a production estimate.**
> Unit prices were pulled from the AWS Price List API on 2026-09-13 (ap-northeast-1). Discounts,
> existing commitments, Savings Plans and EDP are not included.
> **Confirm with the AWS Pricing Calculator before deciding.**

## The conclusion first

**On storage list price alone, the FSx for ONTAP configuration costs more than EBS only.** No
scenario tested reversed that, and raising the VM count to 200 found no crossover point.

**That said, the price difference does not settle the choice.** FlexClone, SnapMirror and
multiprotocol access have no equivalent in the EBS configuration, and some performance
requirements cannot be delivered by a single EBS volume at all. This document goes as far as
presenting the difference; **choosing between them requires reading the difference and the
capabilities together.**

| Scenario | EBS only | EBS + FSx for ONTAP | Difference |
|---|---|---|---|
| One VM, 1,024 GB, 512 MB/s, 5,000 IOPS (Multi-AZ) | $133.68 | $1,164.29 | +$1,030.61 |
| Same, Single-AZ | $133.68 | $661.60 | +$527.92 |
| 20 VMs, 100 GB each, 512 MB/s and 5,000 IOPS aggregate (Multi-AZ) | $288.00 | $1,469.63 | +$1,181.63 |

Monthly USD, with the OS disk (EBS gp3 50 GB) included on both sides.

## Throughput capacity dominates

**The largest line on an FSx for ONTAP bill is throughput capacity, not storage.** Holding
1,024 GB fixed and varying only throughput capacity:

| Throughput capacity | Monthly total | Of which throughput | Share |
|---|---|---|---|
| 128 MB/s | $579.27 | $193.41 | 33.4% |
| 512 MB/s | $1,159.49 | $773.63 | 66.7% |
| 2,048 MB/s | $3,480.39 | $3,094.53 | 88.9% |
| 4,096 MB/s | $6,574.92 | $6,189.06 | 94.1% |

**It is billed on the provisioned amount, so it is charged whether or not it is used.** Size
throughput capacity first, then capacity.

> **The throughput capacity you need cannot be derived by dividing required bandwidth.** In a
> sibling project's measurements, three environments running the same procedure, the same
> template and the same negotiated result spread 2.64x
> ([results](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/1bedd45/docs/ja/verification/perf-matrix-results.md#f-3-と再現性の実測)).
> **This series has not measured it.**

## Multi-AZ versus Single-AZ

**"Single-AZ is half price" holds only for capacity and IOPS.**

| Item | Multi-AZ | Single-AZ | Ratio |
|---|---|---|---|
| SSD storage | $0.300/GB-Mo | $0.150/GB-Mo | 50.0% |
| Capacity pool | $0.0476/GB-Mo | $0.0238/GB-Mo | 50.0% |
| SSD IOPS above the included amount | $0.0408/IOPS-Mo | $0.0204/IOPS-Mo | 50.0% |
| **Throughput capacity** | **$1.511/MBps-Mo** | **$0.906/MBps-Mo** | **60.0%** |
| Capacity pool requests | same | same | 100% |

Because throughput capacity is most of the total, **switching to Single-AZ does not halve the
total.** In the one-VM scenario above it went $1,164.29 → $661.60, which is 56.8%.

Choosing Single-AZ means the file system is unavailable during an AZ failure. **It is not a
choice to make on cost alone.**

## Why storage efficiency does not lower the bill

**Deduplication and compression shrink the data but do not lower the bill by default.** SSD is
billed on the provisioned amount, so **nothing changes until the provisioned capacity is actually
reduced.** What is freed remains as billable headroom.

The same applies to ONTAP snapshots. **Snapshots carry no separate charge but consume the SSD
already provisioned.** They use capacity that is already paid for, which is prepayment rather
than being free.

The distinction is documented in
[the FSx for ONTAP Adoption Playbook's provisioned versus consumed note](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/cost/notes/provisioned-versus-consumed.md).

## Capacity pool request charges

Tiering adds request charges on top of capacity pool storage. **Reads and writes differ by
12.7x.**

| Type | Rate | Per million requests |
|---|---|---|
| Read | $0.00037 / 1,000 | $0.37 |
| Write | $0.0047 / 1,000 | $4.70 |

**"Tiering cold data down saves money" reverses depending on access frequency.** If the tiered
data keeps being read, request charges eat the storage price difference.

## The free EBS baseline, and its per-volume ceilings

**Each EBS volume includes 3,000 IOPS and 125 MB/s at no additional charge.** Splitting the same
aggregate across more volumes multiplies that free allowance, which lowers the EBS bill. FSx for
ONTAP buys throughput capacity once per file system and does not benefit from that shape.

**A single volume does have ceilings, however.**

| Constraint | Value | Source |
|---|---|---|
| gp3 IOPS | 3,000–80,000 | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |
| gp3 throughput | 125–2,000 MiB/s | [General Purpose SSD](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html) |
| gp3 throughput against IOPS | **0.25 MiB/s per provisioned IOPS** (2,000 MiB/s requires 8,000 IOPS) | as above |
| io2 IOPS | 100–256,000 (**256,000 on Nitro instances only; 32,000 otherwise**) | [CreateVolume](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_CreateVolume.html) |

`scripts/cost_comparison.py` detects configurations that violate these ceilings and **still
prints the cost while marking it undeliverable.** Printing a price alone for such a configuration
would put a cheap, unreachable number in the EBS column.

## What this comparison excludes

**What is excluded still appears on the bill.** Each of these either differs between the two
configurations or cannot be ignored under some conditions.

- **EC2 instance cost**: assumed identical in count and type, so it does not appear in the
  difference. It is part of the total
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
# Defaults (Multi-AZ, 1,000 GB, 512 MB/s, 5,000 IOPS)
python3 scripts/cost_comparison.py

# Change the deployment and the requirements
python3 scripts/cost_comparison.py --deployment SINGLE_AZ_1 --data-size 1024 --iops 5000

# When tiering, pass read and write request counts separately
python3 scripts/cost_comparison.py --data-size 1024 \
  --pool-read-requests-millions 500 --pool-write-requests-millions 20

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
