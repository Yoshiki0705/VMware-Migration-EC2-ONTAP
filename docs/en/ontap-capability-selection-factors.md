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

> **A clone inherits the consistency of the snapshot it is based on.**
> FSx for ONTAP snapshots are **crash-consistent by default**, and application consistency requires
> quiescing the database's I/O
> ([source](https://aws.amazon.com/blogs/storage/using-netapp-snapcenter-with-amazon-fsx-for-netapp-ontap-to-protect-your-sql-server-workloads/)).
> **So "clones cannot be application-consistent" is not the case.** A clone taken from a quiesced
> snapshot is application-consistent. See
> [obtaining application consistency](#obtaining-application-consistency).
>
> **What FlexClone removes is the impact on production, not the copy itself.** A host-mediated route
> still produces one copy
> ([FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/reference/comparison/block-to-file-routes.md)).

### Obtaining application consistency

**Snapshots created by the default snapshot policy are not application-consistent.** There are two
approaches, both documented by AWS.

| Approach | Detail | Source |
|---|---|---|
| **SnapCenter** | Application plug-ins (SQL Server, Oracle and others) create consistent snapshots and go on to **protect, replicate and clone** them. **No additional licensing** is required to use it with FSx for ONTAP | [SQL Server](https://aws.amazon.com/blogs/storage/using-netapp-snapcenter-with-amazon-fsx-for-netapp-ontap-to-protect-your-sql-server-workloads/) / [Oracle](https://aws.amazon.com/blogs/storage/protect-your-oracle-databases-on-amazon-ec2-using-netapp-snapcenter-with-amazon-fsx-for-netapp-ontap/) |
| **Quiesce manually** | For Oracle: `ALTER DATABASE BEGIN BACKUP` → `vol snapshot create` → `ALTER DATABASE END BACKUP`, then carry it to the secondary with `snapmirror update -source-snapshot` and clone there | [Cloning](https://aws.amazon.com/blogs/storage/accelerate-development-refresh-cycles-and-optimize-cost-with-amazon-fsx-for-netapp-ontap-cloning/) |

**Three prerequisites apply when using SnapCenter.**

- **Set the volume's snapshot policy to `none`.** Automatic snapshots are not application-consistent,
  and mixing them in makes it unclear at recovery time which ones are usable
- **Separate database workloads across volumes or file systems**
- **Leave at least 0.5% of volume space for clone metadata**

Source: [Oracle best practices](https://aws.amazon.com/blogs/storage/protect-your-oracle-databases-on-amazon-ec2-using-netapp-snapcenter-with-amazon-fsx-for-netapp-ontap/).
**SnapCenter is unverified in this project.**

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

## DR cost, and the condition under which clones make it cheaper

**"Clones consume no capacity, so DR is cheap" becomes correct once the comparator is named.** The
conclusion changes with what it is compared against, so here are three.

2,048 GB protected, 70% efficiency, DR side at 512 MB/s and Single-AZ, no tiering:

| Option | Monthly | RPO | RTO | Test without stopping replication |
|---|---|---|---|---|
| Backup only (no secondary file system) | **$30.72** | Backup interval | **Restore takes time; no standby** | No |
| SnapMirror only | $617.47 | 5 min | Minutes | No |
| **SnapMirror + FlexClone (one DR clone)** | **$617.47** | 5 min | Minutes | **Yes** |

**Two things hold at once.**

**1. The DR clone adds $0.00.** The secondary sits at the 1,024 GiB minimum SSD floor, so one clone's
delta does not move the bill. **If SnapMirror is already in place, testing DR costs nothing extra.**
That is the precise sense in which clones make DR cheaper.

**2. That secondary itself is 20.1x backup-only.** Lowering the DR side's throughput capacity narrows
it but does not close it.

| DR throughput | Backup only | SnapMirror + Clone | Ratio |
|---|---|---|---|
| 128 MB/s | $30.72 | $269.57 | 8.8x |
| 256 MB/s | $30.72 | $385.54 | 12.6x |
| 512 MB/s | $30.72 | $617.47 | 20.1x |

**So the conditions are these.**

| Condition | Cheaper? |
|---|---|
| **A standby at RPO 5 min and RTO minutes is a requirement** | **Yes.** Given that standby, the clone for testing is effectively free |
| Several environments from the same data (DR test + dev + QA) | **Yes**, because capacity does not multiply with them |
| RTO is not a requirement (a slow restore is acceptable) | **No.** Backup-only is 8.8–20x cheaper |
| Does more protected data reverse it? | **No.** The secondary's cost is mostly throughput capacity, which does not scale with data |

**Backup storage is $0.050/GB-month** on consumption, and **storage efficiency is always enabled for
backup data**. Protecting FSx for ONTAP through AWS Backup rests on that same backup charge.

> **Logically air-gapped vault (LAGV) pricing is separate.** The Price List API returned LAGV warm
> storage at $0.0575/GB-month for FSx-Windows, FSx-Lustre and FSx-OpenZFS, but **no LAGV entry for
> FSx for ONTAP was found in that query.** That is "not confirmed by this query", not "unsupported".

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
| **Constraint 1** | **A cache volume cannot be smaller than 50 GB.** Creation fails with `Volumes of this type must be at least 50GB` |
| **Constraint 2** | **The FSx for ONTAP aggregate is FabricPool-enabled, so creation fails unless a tiered aggregate is explicitly permitted** (`Aggregates not matching FabricPool requirements`). It is off by default |
| Source | Measured by a sibling project ([FlexCache verification](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/a97a4ec/docs/ja/verification/flexcache-security-style-inheritance.md)). **Not measured here** |

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

## What applies first when migrating as block

**Carrying a VMware data volume across as a LUN puts block-specific prerequisites ahead of the
capabilities' appeal.** This ground is covered by the block-storage verification in the sibling
[FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook)
(`ap-northeast-1`, second-generation single HA pair, ONTAP 9.18.1P5 series, 2026-09-05). **All of it
is the sibling's measurement, not this project's.** This project's GA verification was one end-to-end
pass of agent-based migration (9.18.1P3D1); the block-specific behaviour below was not measured here.
**The sibling's block notes exist in Japanese only, so the links below point to the Japanese
originals.**

### Narrowed before you choose

| Prerequisite | Detail | Source |
|---|---|---|
| **Protocol is decided before creation** | Whether iSCSI / NVMe/TCP is available narrows by generation, HA-pair count and OS before you choose. **Generation and HA-pair count cannot be changed after creation** | [protocol-choice-is-bounded-before-you-choose](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/protocol-choice-is-bounded-before-you-choose.md) |
| **Block objects are outside the AWS API** | The boundary sits between the volume and the LUN. **A template reaches only as far as the volume**; LUNs and igroups are created via the ONTAP CLI / REST API | [block-objects-are-outside-the-aws-api](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/block-objects-are-outside-the-aws-api.md) |
| **Capacity is counted in three places** | A `space-reserve` LUN consumes volume capacity before a byte is written. When it runs out the LUN **goes read-only** (not a write error) | [capacity-is-counted-in-three-places](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/capacity-is-counted-in-three-places.md) |
| **NVMe/TCP is thin on the AWS side** | The security-group requirements table omits the NVMe/TCP ports (data 4420 / discovery 8009, from the sibling's measurement). iSCSI's 3260 is listed. **Designing the SG from the table alone leaves NVMe/TCP unable to connect** | [nvme-tcp-is-thin-on-the-aws-side](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/nvme-tcp-is-thin-on-the-aws-side.md) |

**For block use, the 6-HA-pair condition arrives first.** See the
[generation section of the cost comparison](tco-comparison.md#only-the-throughput-capacity-rate-changes-by-generation).

### Why post-migration availability and recovery differ from file

**This is the substance of "why EC2 + FSx for ONTAP is a safe choice."** Block availability is built
on a different mechanism from file shares, and designing without knowing it gets it wrong.

| Fact | Detail | Source |
|---|---|---|
| **The host multipath is what switches** | The storage presents multiple paths; I/O continuity is on the host. iSCSI path count moves from 2 to 24 with the chosen session count. **Measured failover: iSCSI had no outage; NVMe/TCP had a 423.8-second break** | [paths-are-the-failover-mechanism](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/paths-are-the-failover-mechanism.md) |
| **Block addresses do not move, even Multi-AZ** | NFS / SMB floating addresses move by route rewrite; iSCSI / NVMe/TCP are fixed addresses inside the VPC CIDR. **They do not trigger the Transit Gateway condition**, and availability is carried by the host multipath | [multi-az-moves-a-route-not-an-address](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/multi-az-moves-a-route-not-an-address.md) |
| **LUN layout decides recovery granularity** | Snapshot / SnapMirror work per volume. One-LUN-per-volume versus grouping is a **recovery-unit** decision, not performance. Right after migration, all of a server's LUNs land in one volume ([GA verification 12.3](atx-fsxn-ga-verification.md)) | [lun-layout-decides-recovery-granularity](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/lun-layout-decides-recovery-granularity.md) |
| **Two controls sit outside the igroup** | CHAP (initiator authentication) and portset (restricting which LIFs expose a LUN). **Neither is documented, but both worked under `fsxadmin`** (the sibling's measurement). With igroups alone, spoofing an IQN reaches the LUN | [igroups-are-not-the-only-access-control](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/igroups-are-not-the-only-access-control.md) |
| **Monitoring has no LUN dimension** | The CloudWatch `AWS/FSx` namespace has neither a LUN nor a protocol dimension. **One-LUN-per-volume makes the volume dimension effectively the LUN dimension.** Per-LUN and p99 come from the ONTAP side | [what-block-monitoring-shows](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/what-block-monitoring-shows.md) |

> **There is a measured migration where crash-consistency is not a problem for a DB on LUNs.** For a
> PostgreSQL with data and WAL on separate LUNs, a consistency-group Snapshot taken without stopping
> writes (**a 0.52-second write fence**, same timestamp on both volumes), started from its clone,
> replayed WAL on its own and **reached consistency in 0.84 seconds**, with every row committed before
> the fence still present. **What works is not the Snapshot type but that the order of dependent writes
> is intact**; a fence is required when it spans multiple LUNs
> ([a-database-on-luns-recovers-without-quiescing](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/a-database-on-luns-recovers-without-quiescing.md),
> PostgreSQL 16 / a single observation). **This project's [clone consistency](#pattern-a-application-development-clone--test--reiterate)
> says application consistency is obtained by quiescing; this measurement is the other side — the DB
> comes up without quiescing.** Do not generalise to other engines.

### Read before you measure — the sibling's block measurement guides

**If you are going to measure performance or protocols yourself, the pitfalls are collected first.**

| Guide | What it holds |
|---|---|
| [Block protocol testing guide](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/main/docs/en/reference/block-protocol-testing-guide.md) | That "single-client 5 Gbps (625 MBps) / required bandwidth = session count" does not hold, that the queue count is not granted on request (36 to 4), the pre-billing check for whether ANA is usable, and the six-hour cooldown after a provisioned-IOPS decrease |
| [ONTAP version matrix](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/main/docs/en/reference/block-protocol-ontap-version-matrix.md) | Which measurement was taken on which ONTAP version. **The primary environment is 9.18.1P3D1 — the same version as this project's GA verification** |
| [AWS feedback status](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/main/docs/en/reference/block-protocol-aws-feedback-status.md) | Block-origin items already filed with AWS. Read alongside this project's [feedback to AWS](atx-fsxn-feedback-to-aws.md) for the full picture |

> **This is the source for the six-hour cooldown.** The provisioned-IOPS cooldown mentioned in the
> [cost comparison](tco-comparison.md#first-generation-file-systems-cannot-decrease-ssd) is measured by
> the testing guide above (decrease direction only; increases unconstrained; the update itself sits in
> `UPDATED_OPTIMIZING` for about 18 minutes).

## Using this when selecting and designing

**Work through it in this order.**

| Step | Question | What it settles |
|---|---|---|
| 1 | How many environments (dev, test, DR, validation) | **Whether FlexClone applies. More environments favour FSx** |
| 2 | Carry block through, or replace it with file | Whether tiering and efficiency apply ([why tiering should not be assumed for block storage](tco-comparison.md#why-tiering-should-not-be-assumed-for-block-storage)). If carrying block through, see [what applies first](#what-applies-first-when-migrating-as-block) |
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
