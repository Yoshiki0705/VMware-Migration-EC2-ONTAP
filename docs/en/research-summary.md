# VMware ESXi to EC2 / FSx for ONTAP: Research Summary

**Date**: 2026-06-03 (updated 2026-06-21)
**Status**: Research phase (pre-verification)

> ⚠️ **The body is a snapshot as of 2026-06-03.** Since then, the AWS Transform FSx for ONTAP destination reached **GA on 30 August 2026**. References to "Public Preview" below reflect the state at that time. [(Primary source for GA)](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/) Hands-on verification after GA is in [the verification report](atx-fsxn-ga-verification.md).

---

## Executive Summary

This project verifies multiple migration paths from VMware ESXi workloads to Amazon EC2 with data disks on Amazon FSx for NetApp ONTAP — specifically **NetApp Shift Toolkit** (Early Preview) and **AWS Transform** (Public Preview, FSx for ONTAP destination).

The verification focuses not just on "migrating from VMware to AWS" but on confirming whether existing ONTAP operational models (Snapshot, FlexClone, SnapMirror, Storage Efficiency) can be preserved while transitioning to cloud-native operations on EC2 + FSx for ONTAP.

> ⚠️ The VMware ESXi → AWS EC2 path is Early Preview. Currently targets data disk placement on FSx for ONTAP only. Specifications may change.

## Key Findings

### Shift Toolkit Capabilities (GA)

- GUI-based VM migration across hypervisors (ESXi, Hyper-V, OpenShift, OLVM, Proxmox)
- ONTAP FlexClone for disk conversion in seconds (1TB VMDK in seconds vs hours)
- Source VM non-destructive (script copy only, immediate rollback possible)
- Prerequisites: ONTAP 9.14.1+, NFS datastore, Windows-only tool
- Free from NetApp

### EC2 Early Preview (Confirmed via Shift Toolkit v8.0 Procedure)

- **Confirmed scope**: Both OS disk (→ EBS → AMI) and data disk (→ FSx for ONTAP iSCSI LUN) are covered
- **OS disk method**: Two approaches — EBS Direct APIs (recommended, next drop) and VM Import/Export (current Preview)
- **Drivers**: cloud-init (Linux) / EC2Launch v2 (Windows) automatically injected
- **Requires**: NetApp-side enablement via the NetApp support alias (address given in the Shift Toolkit v8.0 blog)

### Tool Selection Guidance

| Condition | Recommended Tool |
|-----------|-----------------|
| No ONTAP or EBS-only | AWS MGN |
| ONTAP + FSx for ONTAP data placement + small/mid-scale | Shift Toolkit (Early Preview) |
| ONTAP + large scale (100+ VMs) + near-zero downtime | Cirrus Migrate Cloud |
| Planning & sizing only | BlueXP Migration Advisor | <!-- allow:naming -->

## AWS Transform for FSx for ONTAP (Public Preview, 2026-06)

On 2026-06-16, AWS Transform for migrations added Amazon FSx for NetApp ONTAP as a block-storage destination (in addition to Amazon EBS). Block data can be replicated directly to FSx for ONTAP volumes within the same migration wave as compute and network. ([source](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/))

### Positioning (not mutually exclusive)

AWS Transform is an AWS-native orchestrator that runs the whole migration wave (discovery → planning → compute + network + storage). Shift Toolkit is an ONTAP-native conversion engine. They sit at different layers and are not an either/or choice — AWS Transform can absorb the OS-disk-to-EC2-boot step (the P0 open question for Shift Toolkit) as part of compute migration.

| Aspect | AWS Transform (Public Preview) | Shift Toolkit (Early Preview) |
|--------|-------------------------------|-------------------------------|
| Nature | AWS-native, agentic AI orchestration | NetApp-native, FlexClone conversion engine |
| Coverage | discovery → plan → compute + network + storage in one wave | Mainly disk conversion |
| Source prerequisite | Source-agnostic (on-prem / other cloud / VMware block & NFS) | Source VM must reside on ONTAP NFS datastore |
| FSx for ONTAP role | Block-storage destination (in addition to EBS) | Data disk placement (iSCSI LUN) |
| NetApp touchpoint | discovery ingests NetApp DII (planning phase) | Tool itself is ONTAP / FlexClone based |
| Maturity | Public Preview | Early Preview |

### Root volume (shared physical constraint)

EC2 boots only from an AMI (EBS-backed); it cannot boot directly from an FSx for ONTAP iSCSI LUN. So both approaches converge on: OS/root volume on EBS (subject to the OS support matrix), data volumes on FSx for ONTAP (ONTAP features retained). The difference is who handles the OS-to-EBS step — Shift Toolkit may need a companion tool, while AWS Transform likely absorbs it within compute migration (to be confirmed).

### Supported OS — the legacy-OS reality (as of 2026-06)

The AWS Transform rehost engine is AWS Transform MGN (formerly AWS Application Migration Service), which has a defined OS support matrix. Current support centers on Windows Server 2016+ and RHEL up to 9.x; legacy/EOL guests are sunsetting (RHEL/CentOS 5.x already EOL, CentOS 6/7/8 and RHEL 6.x deprecating through 2026, 32-bit Linux unsupported). ([MGN supported OS](https://docs.aws.amazon.com/mgn/latest/ug/Supported-Operating-Systems.html)) Shift Toolkit also has OS constraints, so the practical lever is decoupling OS boot (EBS, matrix-bound) from data (FSx for ONTAP), not claiming any single tool "solves" legacy OS.

### Cost structure (as of 2026-06)

AWS Transform agents for Assessment / Windows / Mainframe / VMware migration are free; only the Custom transformation agent is paid ($0.035 / agent-minute). AWS infrastructure provisioned from the output (EC2, EBS, FSx for ONTAP, data transfer, etc.) is billed at standard rates. ([pricing](https://aws.amazon.com/transform/pricing/)) "Service is free" must not be read as "the whole migration is free" — infrastructure design (FSx for ONTAP sizing, Storage Efficiency) drives the real cost.

> ⚠️ Public Preview / point-in-time (2026-06). The "AWS-native replication" and "auto EBS-boot" points are estimates pending NetApp/AWS confirmation. Re-verify against current docs before publishing.

## Success Criteria

| Metric | Target |
|--------|--------|
| Data disk conversion | < 5 min per 100GB (FlexClone minimizes conversion time; copy-based approaches are dominated by transfer time) |
| Cutover downtime | < 30 min (small VMs) |
| Data integrity | 100% sha256sum match |
| FSx for ONTAP iSCSI performance | Baseline comparison with documented fio parameters |
| Cost comparison | EBS-only vs EBS + FSx for ONTAP hybrid |

## Verification Phases

1. **Environment Setup** — VPC, FSx for ONTAP (Multi-AZ), EC2, VPN/DX
2. **Migration Test** — Shift Toolkit execution, evidence collection
3. **Validation** — Performance benchmarks, ONTAP features, cost analysis
4. **Documentation** — Blog series, architecture diagrams, reusable templates

## References

- [Shift Toolkit Overview](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)
- [Migrate VMs to Amazon EC2](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/migrate-vms-to-ec2-fsxn-overview.html)
- [AWS Storage Blog: Seamless VMware Migration](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/)
- [AWS Storage Blog: BlueXP Migration Advisor](https://aws.amazon.com/blogs/storage/expedite-vmware-migration-to-amazon-ec2-and-amazon-fsx-for-netapp-ontap-using-bluexp-workload-factory-for-aws-migration-advisor/) <!-- allow:naming -->
- [Amazon FSx for NetApp ONTAP](https://aws.amazon.com/fsx/netapp-ontap/)

---

*Full research report (Japanese): [docs/ja/research.md](../ja/research.md)*
