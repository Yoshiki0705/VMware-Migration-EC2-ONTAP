# Treating ONTAP capabilities as selection factors

Evaluating Amazon FSx for NetApp ONTAP on capacity price alone drops the capabilities **that have no
EBS equivalent, or whose EBS equivalent carries a separate charge**. This document lists each
capability with what it does, what EBS requires instead, how it affects cost and time, and its
constraints, so it can be used when selecting and designing.

> **The cost figures are in [the cost comparison](tco-comparison.md).** This document covers what
> capacity price cannot express. **Neither one alone supports the decision.**

## The conclusion first

**The capability gap remains even where tiering cannot be assumed.** It matters most when **many
environments are built from the same data**: EBS grows with the number of environments, while
FlexClone shares blocks with the parent and does not.

500 GB golden image, 10% rewritten per environment, `snapshot-only` (no tiering):

| Environments | Billed logical capacity (FSx / EBS) | Ratio | FSx monthly | EBS monthly |
|---|---|---|---|---|
| 0 | 500 / 500 GB | 1.00 | $1,080.83 | $73.00 |
| 10 | 1,000 / 5,500 GB | 5.50 | $1,080.83 | $553.00 |
| 20 | 1,500 / 10,500 GB | 7.00 | $1,080.83 | $1,033.00 |
| **30** | 2,000 / 15,500 GB | 7.75 | **$1,080.83** | $1,513.00 |
| 50 | 3,000 / 25,500 GB | 8.50 | **$1,111.13** | $2,473.00 |

**EBS is cheaper while there are few environments, and it crosses over at 30.** Enabling **Fast
Snapshot Restore on the EBS side brings the crossover down to 10** (below).

**The 10% per environment is derived from an example NetApp publishes.** For a 100 GB production
database with one full mirror and six development and test copies, the usual total is 800 GB, whereas
using FlexClone for the DevTest copies keeps it to 260 GB — **a 67% reduction**
([source](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)).
Dividing the 60 GB difference across six copies gives 10% each. **That is NetApp's published example,
not a measurement from this project.**

### Why this holds for block storage too

**This difference does not depend on tiering, so it holds for block.** What AWS documents is
volume-level cloning, but
[a LUN is hosted inside a volume](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/create-iscsi-lun.html),
so cloning the volume clones the LUN with it.

**Unverified**: whether `lun clone` or file clone can be used on their own on FSx for ONTAP. NetApp's
article describes cloning volumes, LUNs and files, but **what could be confirmed in AWS documentation
is volume-level cloning.**

## Architecture patterns

Organised from the two workflows and the placement diagram in NetApp's article
([source](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)).
The diagrams are not reproduced; their content is rewritten as configurations.

### Pattern A: application development (Clone → Test → Reiterate)

| Stage | Operation | Where it helps |
|---|---|---|
| Clone | Create thin clones of production datasets | No capacity consumed, and the wait is only the creation time |
| Test | Test on real data without impacting production | Production data, but **the consistency is crash-consistent** (below) |
| Reiterate | Recreate clones to test against current data | **Avoids testing against data that has gone stale** |

**The pattern assumes clones are discarded and recreated each cycle.** Splitting a clone ends the
sharing, and the capacity benefit goes with it.

> **A clone is crash-consistent and carries no application-level guarantee.** A snapshot of a LUN is
> crash-consistent by default, so `fsck` or `chkdsk` may run when the clone is mounted. **"Testing
> against production data" is not "getting production's consistency."** If application consistency is
> required, arrange a quiesce point separately
> ([FSx for ONTAP Adoption Playbook: routes from block to file](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/reference/comparison/block-to-file-routes.md)).
>
> **What FlexClone removes is the impact on production, not the copy itself.** A host-mediated route
> still produces one copy.

### Pattern B: disaster recovery (Mirror → Test → Activate)

| Stage | Operation | Where it helps |
|---|---|---|
| Mirror | Replicate to the secondary with SnapMirror | RPO 5 minutes, RTO single-digit minutes |
| Test | **Validate the DR copy without stopping replication** | Validation runs on a clone of the DR volume, so SnapMirror keeps replicating into the parent |
| Activate | Fail over to the secondary on disaster | — |

**Not having to stop replication in order to validate is the point of this pattern.** The
[S&P Global case study](https://aws.amazon.com/blogs/architecture/sp-globals-innovative-disaster-recovery-strategy-using-amazon-fsx-for-netapp-ontap-snapshots/)
follows this shape and reports FlexClone creation completing in under two minutes.

### How a clone is composed (three layers)

NetApp's diagram presents a clone as three layers.

| Layer | Content |
|---|---|
| Active volume | The live volume being cloned |
| Snapshot | A point-in-time image of that volume. **It is the base of the clone** |
| FlexClone | A **transparent writable layer** placed in front of the snapshot |

**A clone depends on its base snapshot.** The AWS API carries a `DELETE_CLONED_VOLUMES` option for
deleting "snapshot clones on the destination volume", which shows clones and snapshots are bound
together. **Do not design an operation that deletes the base snapshot.**

### Placement, and the cost that follows from it

NetApp's placement diagram puts Parent (Prod), Clone1 (Dev) and Clone2 (QA) on one aggregate on the
primary side, and DR Replica plus DR Clone on a separate aggregate on the secondary side. **Two
design consequences follow.**

**1. Dev and QA clones share the primary side's provisioned resources.** AWS explains that an SSD
decrease pauses on FlexClones because "ONTAP splits clone relationships while moving volumes, which
would result in duplicated storage on the new disks"
([source](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ssd-decrease-troubleshooting.html)) — so
clones share the parent's disks, and **SSD capacity, IOPS and throughput capacity all come from the
primary file system.** Clones do not inherit the parent's QoS, so **bound them with a QoS policy
group as the count grows.**

**2. The secondary is a separate file system, so the minimum SSD and the throughput capacity apply
again.** For a 2,048 GB parent, 10% delta, 512 MB/s, no tiering:

| Configuration | Primary | Secondary | Total |
|---|---|---|---|
| Single-AZ secondary | $1,080.83 | $617.47 | **$1,698.30** |
| Multi-AZ secondary | $1,080.83 | $1,080.83 | **$2,161.66** |

**The secondary breaks down as $153.60 for 1,024 GiB of SSD and $463.87 for throughput capacity —
throughput is 75% of it.** Neither shrinks because the DR clone is small. **"Clones consume no
capacity, so DR is cheap" does not follow.**

## Capability by capability

### FlexClone — writable copies that consume no capacity

**A clone shares data blocks with its parent and consumes no storage for the shared data**
([FSx features](https://aws.amazon.com/fsx/netapp-ontap/features/)). Only rewritten blocks add
capacity.

| Aspect | Detail |
|---|---|
| EBS equivalent | Create a new volume from a snapshot. **Every environment is billed at full capacity** |
| Creation time | Under **2 minutes** in a DR case study AWS published ([S&P Global](https://aws.amazon.com/blogs/architecture/sp-globals-innovative-disaster-recovery-strategy-using-amazon-fsx-for-netapp-ontap-snapshots/)) |
| Cost of "instantly at full performance" on EBS | **Fast Snapshot Restore is required**, billed per snapshot per AZ per hour — about $648/month for one snapshot in one AZ in Tokyo ($0.90/hour × 720). Without it, a restored volume is lazily loaded and performs below par until initialised ([source](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-fast-snapshot-restore.html)) |
| **Constraint 1** | **Clones do not inherit the parent's QoS limits.** Thirty developers with thirty clones can affect production, so a QoS policy group is needed to bound them ([source](https://aws.amazon.com/blogs/storage/using-quality-of-service-in-amazon-fsx-for-netapp-ontap/)) |
| **Constraint 2** | **Creating a clone during an SSD decrease pauses the decrease.** ONTAP splits clone relationships when moving volumes, and the operation resumes only after the clones are deleted ([source](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ssd-decrease-troubleshooting.html)) |
| Constraint 3 | The volume limit (500 on first-generation) bounds the number of environments |
| **Constraint 4** | **Splitting a clone from its parent requires additional disk space.** It ends the sharing, so the capacity benefit goes with it |
| Automation | Creatable through the ONTAP REST API and CLI, so **it fits into a CI/CD pipeline** |

**Where it applies.** Building development, test, staging and schema-validation environments from the
same production data; holding a DR environment as a copy of production; validating a release against
production-equivalent data. **The gap widens with the number of environments.**

**The DR combination is particularly effective.** While a clone of the DR volume is being used for
validation, SnapMirror keeps replicating into the parent volume. **Replication does not have to be
stopped to validate**
([NetApp](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/),
[S&P Global](https://aws.amazon.com/blogs/architecture/sp-globals-innovative-disaster-recovery-strategy-using-amazon-fsx-for-netapp-ontap-snapshots/)).

**On the development cycle**, NetApp cites a games company: moving source code to a new instance went
from hours to minutes, and with hundreds of instances testing in parallel, per-copy capacity charges
were no longer incurred
([source](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/)).
**The company is not named, and this is not a measurement from this project.**

### Snapshot — point-in-time images that consume only what changed

| Aspect | Detail |
|---|---|
| Billing | **No separate charge; they consume provisioned SSD.** Only changed portions are consumed |
| EBS equivalent | EBS Snapshot, **stored in S3 at $0.05/GB-month** (archive $0.0125/GB-month, retrieval $0.03/GB) |
| Constraint | **Snapshots are not included in backups.** They have to be considered separately |

### SnapMirror — volume-level replication and DR

| Aspect | Detail |
|---|---|
| What it does | In-Region and cross-Region replication with **RPO as low as 5 minutes and RTO in single-digit minutes** ([FSx features](https://aws.amazon.com/fsx/netapp-ontap/features/)) |
| EBS equivalent | Snapshot copy, or application-level replication. **Block-level replication is yours to build** |
| **Constraint 1** | **Volume-level only. SVM DR (SVMDR) is not supported** |
| **Constraint 2** | **Synchronous SnapMirror, including StrictSync, is not supported.** RPO 0 is not available ([source](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/scheduled-replication.html)) |
| Combination | A FlexClone at the DR site allows **validation without stopping replication** (the S&P Global case above) |

### FlexCache — read-heavy distributed access

| Aspect | Detail |
|---|---|
| What it does | A sparsely populated cache that fetches only what is needed. Works on-premises ↔ FSx and FSx ↔ FSx |
| Suits | **Read-intensive workloads with infrequent changes.** Changes to the origin require the cache to refresh |
| EBS equivalent | None ([source](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)) |

### Multiprotocol — NFS, SMB, iSCSI and NVMe to the same volume

| Aspect | Detail |
|---|---|
| What it does | The same data is reachable over several protocols, so a later move (EC2 to ECS or EKS) does not change the data layer |
| EBS equivalent | **None.** Shared access needs another service, and Multi-Attach is one AZ only, io1/io2 only, cannot boot, and requires a clustered file system |

### Storage efficiency — compression, deduplication, compaction

| Aspect | Detail |
|---|---|
| Published figure | **70% for virtual servers and desktops** ([source](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html)) |
| EBS equivalent | None |
| **Constraint** | **Post-process compression is off by default** in ONTAP because of its performance impact. Enabling it needs diagnostic privilege, so **the published figure cannot be assumed as-is** |

### SnapLock — WORM protection

| Aspect | Detail |
|---|---|
| What it does | Prevents modification and deletion for a retention period, with legal holds available |
| EBS equivalent | None. **Snapshot locks and IAM controls are not the same thing as file-level WORM inside a volume** |
| Note | Tiering to the capacity pool works on SnapLock volumes |

### QoS — per-volume IOPS and throughput ceilings

| Aspect | Detail |
|---|---|
| What it does | Policy groups set ceilings, shared or non-shared |
| EBS equivalent | Provisioned per volume, so **the ceiling is set by purchase rather than by configuration** |
| **Constraint** | **Clones do not inherit the parent's policy** (the same as FlexClone constraint 1) |

### Backups

| Aspect | Detail |
|---|---|
| What it does | Automatic daily per-volume backups, incremental and crash-consistent |
| Billing | On consumption |
| **Constraint** | **A final backup is taken by default when a volume is deleted, and it keeps billing if left behind** ([teardown](quickstart.md#delete-stack)) |

## Using this when selecting and designing

**Work through it in this order.**

| Step | Question | What it settles |
|---|---|---|
| 1 | How many environments (dev, test, DR, validation) | **Whether FlexClone applies. More environments favour FSx** |
| 2 | Carry block through, or replace it with file | Whether tiering and efficiency apply. See [why tiering should not be assumed for block storage](tco-comparison.md#why-tiering-should-not-be-assumed-for-block-storage) |
| 3 | The RPO and RTO requirement | Whether SnapMirror suffices (**RPO 0 is not available**), and what to build on the EBS side |
| 4 | The availability commitment | See [comparing at matched availability](tco-comparison.md#comparing-at-matched-availability-9999) |
| 5 | Immutability and audit requirements | Whether SnapLock is needed. EBS has no equivalent |
| 6 | Planned re-placement after migration | Whether multiprotocol is needed (EC2 to ECS, EKS or Fargate) |

**Capacity price comes second at the earliest.** Step 1 often sets the direction on its own, and
**where there are many environments, FSx for ONTAP is favoured without assuming tiering.**

## Reproducing this

```bash
# 30 environments from a golden image, no tiering, 10% delta
python3 scripts/cost_comparison.py --data-size 500 --clone-count 30 \
  --clone-delta-ratio 0.10 --tiering-policy snapshot-only
```

## What has not been verified

- **The per-environment delta ratio has to be measured.** The 10% default is derived from NetApp's
  published example, not measured here
- **Whether `lun clone` or file clone can be used on their own on FSx for ONTAP is unverified**
- **This project has not measured FlexClone creation time.** The under-two-minutes figure comes from
  a case study AWS published about another organisation, not from this configuration
- The performance impact of many clones is unmeasured, as is the effect on production when QoS is
  left unset

## Related documents

| Document | Contents |
|---|---|
| [Cost comparison](tco-comparison.md) | Capacity price and the matched-availability comparison |
| [Migration method comparison](migration-method-comparison.md) | Which tool to migrate with |
| [Quickstart](quickstart.md) | Building and tearing down the environment |

Reference: [NetApp: reduce costs and increase efficiency with FSx for ONTAP cloning](https://www.netapp.com/ja/learn/aws-fsxn-blg-reduce-costs-and-increase-efficiency-with-fsx-for-ontap-cloning/) (the technical statements in this document are sourced from AWS documentation)
