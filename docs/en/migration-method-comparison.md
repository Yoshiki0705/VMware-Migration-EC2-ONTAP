# VMware → EC2 + FSx for ONTAP Migration Method Comparison

**Purpose**: Compare the major approaches for migrating VMware VMs to AWS, organizing applicability conditions, constraints, migration time, downtime, and Amazon FSx for NetApp ONTAP utilization for each method.

**Last Updated**: 2026-06-29  
**Status**: Draft (prepared for partner meeting)

---

## 1. Methods Under Comparison

| # | Method | Overview |
|---|--------|----------|
| A | **NetApp Shift Toolkit** | Migrate VMs on ONTAP NFS datastores to EC2 + FSx for ONTAP via SnapMirror + FlexClone |
| B | **AWS Transform** | AWS-native agent-based migration service. Evolved from former MGN. Agentic AI-based UI |
| C | **VM Import/Export** | The most orthodox approach: AMI creation from VMDK via S3 |
| D | **Veeam Restore to EC2** | Restore to EC2 from existing Veeam backups |

---

## 2. Comparison Table

| Aspect | Shift Toolkit | AWS Transform | VM Import/Export | Veeam Restore to EC2 |
|--------|--------------|---------------|-----------------|---------------------|
| **Primary use case** | Migrate VMware VMs to EC2 + FSx for ONTAP | AWS-native migration planning & execution (discovery → cutover) | Convert VM images to AMI | Restore from backups to EC2 |
| **FSx for ONTAP utilization** | ◎ Strong. Data disks placed directly as iSCSI LUNs | ◎ FSx for ONTAP destination is GA (30 Aug 2026). Data disks placed directly as iSCSI LUNs | △ Primarily EBS. FSx for ONTAP requires separate design | △ Primarily EBS. FSx for ONTAP requires separate design |
| **Boot disk** | EBS (VMDK → RAW → S3 → AMI) | EBS (MGN agent handles automatically) | EBS (AMI via import-image) | EBS (Veeam handles EC2 conversion) |
| **Data disk** | FSx for ONTAP iSCSI LUN (FlexClone-based) | EBS or FSx for ONTAP (Preview) | Primarily EBS | Primarily EBS. FSx for ONTAP requires separate design |
| **Source environment prerequisite** | VMs on ONTAP NFS datastore **required** | Any VMware environment (ONTAP not required) | Any (as long as VMDK/OVA can be exported) | VMs backed up by Veeam |
| **Downtime** | 30 min–2.5 hours (measured: ~1h 49min for 50GB boot disk) | Continuous replication → short cutover (estimate: minutes–10 min) | Long (hours to half a day, proportional to disk size) | Reducible with incremental backups |
| **Replication method** | SnapMirror (pre-sync + final update) | MGN agent (continuous block sync) | None (one-shot copy) | Veeam incremental backup |
| **Large VM suitability** | Expected improvement in 8.1 (EBS Direct API) | High (continuous replication minimizes size impact) | Low (time increases proportionally with S3 upload + import) | Depends on Repository bandwidth |
| **OS restrictions** | See Shift Toolkit support matrix (partially VM Import dependent) | See MGN support matrix | [Many restrictions](https://docs.aws.amazon.com/vm-import/latest/userguide/prerequisites.html) (EOL OS, P2V, i386 unsupported, etc.) | Possibly VM Import dependent (to be confirmed) |
| **Operability** | Dedicated GUI (Blueprint-based) | Agentic AI (chat-based UI) + console | CLI-centric (aws ec2 import-image) | Veeam GUI (Restore to EC2 wizard) |
| **Maturity** | Early Preview (EC2 migration path) | GA (both EBS and FSx for ONTAP targets) | GA (long history) | GA (familiar to Veeam users) |
| **Tool cost** | Free | Free (VMware migration agent) | Free | Veeam license required |
| **Network transformation** | Manual (Network Mapping via Blueprint) | AI auto-generated (vSwitch → VPC/SG mapping) | Manual | Manual |
| **ONTAP operational continuity** | ◎ Native ONTAP features (Snapshot/SnapMirror/Efficiency) continue after SnapMirror break | △ To be verified (Snapshot lineage continuity unclear) | ✕ Treated as new volume | ✕ Treated as new volume |
| **Multi-disk configuration** | ◎ boot=EBS, data=FSx for ONTAP iSCSI handled in same workflow | ○ Handled within same wave (FSx for ONTAP target in Preview) | △ Each disk requires individual processing | △ Additional disks require separate design |

---

## 3. Method Selection Guide

### 3.1 Quick Decision Flow

```text
Q1: Are source VMs on an ONTAP NFS datastore?
├─ No → Go to Q4
│
└─ Yes
    Q2: Migration scale?
    ├─ Large (100+ VMs / multi-account / automated NW transformation needed)
    │   → Recommend AWS Transform
    │
    └─ Small-to-medium / PoC
        Q3: Downtime requirement?
        ├─ Must minimize (minutes-level) → AWS Transform (continuous replication)
        └─ 30 min–2 hour planned outage acceptable → Shift Toolkit

Q4: Source is not ONTAP NFS
    Q5: Existing Veeam environment?
    ├─ Yes → Consider Veeam Restore to EC2
    └─ No
        Q6: Scale / automation requirements?
        ├─ Large / automation required → AWS Transform
        └─ Small / one-off → VM Import/Export (simplest)
```

### 3.2 Recommended Method by VM Characteristics

| VM Characteristic | Recommended Method | Reason |
|-------------------|-------------------|--------|
| Boot disk only (C drive only) | AWS Transform or Shift Toolkit | Both support this; choose by scale |
| Multi-disk configuration (C + D drive, etc.) | Shift Toolkit or AWS Transform (Preview) | Automatic placement on FSx for ONTAP |
| Large VM (500GB+) | AWS Transform | Continuous replication minimizes size impact |
| Legacy OS (Windows 2012, etc.) | VM Import + manual adjustment | Shift Toolkit / Transform may not support |
| Short-downtime requirement (minutes-level) | AWS Transform | Continuous replication + final sync only |
| Existing Veeam environment | Veeam Restore to EC2 | No additional tools needed; leverages incremental backups |
| Active FSx for ONTAP utilization | Shift Toolkit | FlexClone-based fast LUN conversion; ONTAP lineage maintained |

---

## 4. Downtime Comparison (Measured / Estimated)

| Method | 50GB boot disk | 100GB boot disk | Notes |
|--------|---------------|-----------------|-------|
| **Shift Toolkit** | **Measured: ~1h 49min** | Estimate: 2–3 hours | S3 upload (68min) + AMI import (36min) dominate |
| **AWS Transform** | Estimate: 5–15 min | Estimate: 5–15 min | Continuous replication makes boot size less impactful |
| **VM Import/Export** | Estimate: 2–2.5 hours | Estimate: 4–5 hours | Full pipeline: VM stop → export → S3 → import |
| **Veeam** | Estimate: TBD | Estimate: TBD | Depends on incremental backup frequency and Repository performance |

> **⚠️ distinction discipline**: Shift Toolkit value is measured. AWS Transform / VM Import / Veeam are estimates. Will be updated to confirmed values after hands-on testing.

### Shift Toolkit Measured Data Breakdown

```text
SnapMirror-related (steps 1-6):   ~3min 51sec (3.5% of total)
VMDK → RAW conversion:            12.7sec (negligible)
S3 upload:                         68min 5.1sec (62% of total)  ← Bottleneck #1
AMI import:                        36min 20.6sec (33% of total) ← Bottleneck #2
EC2 launch:                        15.1sec
```

**Shift Toolkit 8.1 improvement outlook**: EBS Direct API will eliminate the S3 + AMI import steps, estimated to reduce downtime to **5–15 minutes**.

---

## 5. Key Considerations for Each Method

### 5.1 Shift Toolkit

**Strengths:**

- FlexClone-based data disk conversion (size-independent, sub-second)
- Direct iSCSI LUN placement on FSx for ONTAP
- Native ONTAP feature continuity (Snapshot/SnapMirror/Efficiency) after SnapMirror break
- Blueprint-based batch management via GUI

**Considerations:**

- Source VMs must be on an ONTAP NFS datastore
- Current version has S3 → AMI import bottleneck (to be resolved in 8.1)
- Early Preview — specifications may change
- Guest OS preparation (cloud-init / EC2Launch / iSCSI initiator) is manual
- For multi-disk configurations, Windows Firewall / SSM Agent / iSCSI communication pre-configuration is critical

### 5.2 AWS Transform

**Strengths:**

- Source-environment agnostic (ONTAP not required)
- Short cutover via continuous replication
- End-to-end orchestration: discovery → planning → NW transformation → execution
- Interactive operation via Agentic AI
- Multi-account / large-scale migration support
- EBS-target migration is GA (mature)

**Considerations:**

- The FSx for ONTAP destination reached GA on 30 August 2026. The boot disk is always Amazon EBS
- ONTAP Snapshot lineage continuity unclear (likely created as new LUN/volume)
- Replication agent installation required on source VMs
- Staging EBS costs during continuous replication
- AWS Organizations + IAM Identity Center setup required

### 5.3 VM Import/Export

**Strengths:**

- Simplest and most orthodox approach
- No additional tools required (AWS CLI only)
- Suitable for small-scale, one-off migrations

**Considerations:**

- **Long downtime** (entire pipeline from VM stop → export → S3 upload → import is downtime)
- No incremental sync (one-shot copy)
- Many OS restrictions (EOL OS, P2V origin, i386 unsupported, UEFI constraints, etc.)
- i386 architecture support discontinued after 2026-04-01
- Individual processing required for multiple disks
- Impractical duration for large VMs

### 5.4 Veeam Restore to EC2

**Strengths:**

- No additional tools if Veeam environment exists
- Easy GUI operation
- Downtime reduction possible if leveraging incremental backups
- Easy to position for DR / test restore use cases
- No agent installation on VM guest in some cases

**Considerations:**

- May be subject to VM Import-equivalent constraints internally (to be confirmed)
- FSx for ONTAP data disk placement requires separate design
- Veeam license, environment setup, and Repository placement design required
- Network bandwidth and Repository performance can become bottlenecks
- Operational design and procedure standardization needed for production use

---

## 6. Combination Patterns

Methods are not mutually exclusive; they can be combined based on VM characteristics:

```text
Pattern A: AWS Transform standalone
  → Simplest. Source-environment agnostic. Suited for large scale.

Pattern B: Shift Toolkit standalone
  → FlexClone fast conversion effective in existing ONTAP environments. Suited for small-to-medium / PoC.

Pattern C: AWS Transform (planning + NW) + Shift Toolkit (storage conversion)
  → Large-scale planning/NW via Transform, data migration via Shift Toolkit.

Pattern D: Mixed methods (different methods per VM characteristics)
  → Example: Regular VMs via AWS Transform, large VMs on ONTAP NFS via Shift Toolkit,
       legacy OS via VM Import, existing Veeam VMs via Veeam.
```

---

## 7. Open Questions for Partner Meeting

### AWS Transform

- [ ] Tokyo region availability of FSx for ONTAP destination Preview
- [ ] Boot/data disk placement control for multi-disk VMs
- [ ] Feature differences from former MGN
- [ ] Measured cutover downtime (field experience)

### Shift Toolkit

- [ ] VM Import dependency scope in current version
- [ ] Step reduction details with EBS Direct API in 8.1
- [ ] SSM Agent / iSCSI prerequisites for multi-disk configurations

### VM Import

- [ ] Recent OS support considerations
- [ ] Typical failure cases from past projects
- [ ] Customer communication approach for EOL OS inclusion

### Veeam

- [ ] Confirm whether Restore to EC2 internally uses VM Import
- [ ] Whether VM Import OS restrictions apply equally
- [ ] Configuration patterns for using FSx for ONTAP as data disks

---

## 8. Next Actions

| Task | Owner | Due |
|------|-------|-----|
| Organize Shift Toolkit verification results | NetApp (internal) | This week |
| Document success conditions for multi-disk configuration | NetApp (internal) | This week |
| Create job in AWS Transform Workspace and execute test migration | NetApp (internal) | Early next week |
| Confirm FSx for ONTAP target limitations in AWS Transform | Partner SA / NetApp | Early next week |
| Organize VM Import target OS and restrictions | Partner SA / NetApp | Early next week |
| Verify Veeam Restore to EC2 | NetApp (internal) | Next week |
| Complete comparison table draft | NetApp (internal) | Next week |
| Review customer-facing explanation perspectives | All | Next meeting |

---

## Related Documents

- [Shift Toolkit EC2 Migration Procedure](./shift-toolkit-ec2-procedure.md)
- [AWS Transform Migration Procedure](./aws-transform-migration-procedure.md)
- [VM Import/Export Procedure](./vm-import-procedure.md)
- [FSx for ONTAP iSCSI Setup Guide](./fsxn-iscsi-setup.md)
- [Research Summary](./research-summary.md)
