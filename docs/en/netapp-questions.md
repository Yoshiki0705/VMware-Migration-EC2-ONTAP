# NetApp Confirmation Items — VMware → EC2 / FSx for ONTAP Migration

> Purpose: Confirm migration paths based on Shift Toolkit (Early Preview) and AWS Transform (FSx for ONTAP destination reached GA on 30 August 2026).
> All items are technical questions based on publicly available information; no customer-specific
> details, company names, or internal identifiers are included.

**Background (public information):**

- NetApp Shift Toolkit offers VMware ESXi → Amazon EC2 / FSx for ONTAP migration as Early Preview
- 2026-06-16: AWS Transform for migrations supports Amazon FSx for NetApp ONTAP as a migration destination (Public Preview)
  - [AWS What's New](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/)
- 2026-06-19: Shift Toolkit v8.0 release — EC2 + FSx for ONTAP officially announced as Early Preview
  - [Tech ONTAP Blog: What's New in Shift v8.0](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)
- 2026-06-22: Official procedure document "Migrate VMs from VMware to AWS EC2 and FSx for ONTAP — Shift UI" obtained
  - End-to-end flow confirmed: OS disk → EBS → AMI + data disks → FSx for ONTAP LUN (iSCSI)

---

## Answer Status Legend

| Status | Meaning |
|--------|---------|
| ✅ Confirmed | Answered via public blog / documentation |
| 🔶 Partial | Information available but further detail needed |
| ⬜ Unanswered | Not covered in blog / documentation — confirmation required |

---

## 1. OS / Root Disk Boot Method (Highest Priority)

Confirming the physical constraint that EC2 can only boot from an AMI (EBS-backed) and cannot boot directly from an FSx for ONTAP iSCSI LUN.

| # | Question | Priority | Status |
|---|----------|----------|--------|
| Q1 | Does the Shift Toolkit Early Preview include OS disk AMI conversion, or only data disk placement on FSx for ONTAP? | Critical | ✅ Confirmed |
| Q2 | Are there anticipated cases where the OS disk requires a separate tool (VM Import/Export, AWS MGN, etc.)? | Critical | ✅ Confirmed |
| Q3 | Is a standard procedure provided for creating an AMI from the intermediate format (RAW/QCOW2) converted by Shift Toolkit? | High | ✅ Confirmed |
| Q4 | Are post-launch OS modifications required on EC2 (Nitro drivers, ENA, NVMe support) automated or manual? | High | ✅ Confirmed |

### Q1–Q4 Answer Basis (Official Shift Toolkit EC2 Procedure, 2026-06)

**Primary source**: "Migrate VMs from VMware to AWS EC2 and FSx for ONTAP" — Shift Toolkit UI documentation

- **Q1**: ✅ **Includes OS disk AMI conversion.** Two methods provided:
  1. **Amazon EBS Direct APIs** (recommended, fastest): Creates EBS snapshot directly
  2. **AWS VM Import/Export**: VMDK → RAW → S3 upload → AMI conversion
  - In the current Preview release, only S3 import/export is enabled. EBS Direct APIs will be enabled in the next drop.

- **Q2**: ✅ **No separate tool required.** Shift Toolkit processes the end-to-end flow: OS → EBS → AMI + Data → FSx for ONTAP LUN. The workflow uses VM Import/Export internally, but users do not need to operate separate tools.

- **Q3**: ✅ **Automated as a standard procedure.** Flow documented in the procedure:
  1. Boot disk VMDK → RAW conversion (via ONTAP CLI)
  2. Upload RAW to S3 bucket
  3. Register as AMI via AWS VM Import/Export
  - User operation is limited to Blueprint creation → Migrate button in the Shift Toolkit UI.

- **Q4**: ✅ **Automated.** Explicitly stated in the procedure:
  > "Shift toolkit is intelligent to automatically install the necessary cloud-init drivers"
  - **Linux**: cloud-init + EC2 datasource + Chrony automatically installed (Ubuntu/Debian, SUSE each supported)
  - **Windows**: EC2Launch v2 automatically installed (MSI silent install)
  - **ENA driver**: Injected during prepareVM phase (currently disabled in Preview, to be enabled in next build)
  - **VMware Tools**: Automatically removed on the target
  - **Note**: Automatic prepareVM execution is disabled in the current Preview version. Will be enabled in the next drop. Manual preparation commands are documented in the procedure.

## 2. Relationship Between AWS Transform and Shift Toolkit

| # | Question | Priority | Status |
|---|----------|----------|--------|
| Q5 | Does AWS Transform's FSx for ONTAP migration internally use Shift Toolkit / FlexClone / SnapMirror, or AWS-native block replication? | Critical | ⬜ Unanswered |
| Q6 | Is the NetApp DII integration limited to AWS Transform's discovery (planning) phase only, or does it extend to the migration execution phase? | High | ⬜ Unanswered |
| Q7 | What is NetApp's guidance for customers on choosing between Shift Toolkit and AWS Transform (replacement / complement / coexistence)? | High | ⬜ Unanswered |
| Q8 | Is a configuration where AWS Transform handles compute (root = EBS) and Shift Toolkit handles data (FSx for ONTAP) a supported recommended architecture? | High | ✅ Confirmed |

### Q8 Answer Basis (Official Shift Toolkit EC2 Procedure, 2026-06)

Shift Toolkit itself implements "OS = EBS (AMI), data = FSx for ONTAP (iSCSI LUN)" as its standard architecture. Migration flow from the procedure:
1. Boot disk VMDK → RAW → S3 → AMI registration
2. Data disk VMDK → converted to LUN on FSx for ONTAP
3. Launch EC2 instance from AMI
4. Attach data disks to EC2 guest via iSCSI

Division of labor with AWS Transform is a separate discussion. Shift Toolkit alone can complete this architecture end-to-end.

> **Note**: Q5–Q7 are not addressed in either the Shift Toolkit procedure or blog. The relationship with AWS Transform requires separate confirmation with both AWS and NetApp.

## 3. FSx for ONTAP Specifications as Migration Destination

| # | Question | Priority | Status |
|---|----------|----------|--------|
| Q9 | Is AWS Transform's FSx for ONTAP destination block-only (iSCSI LUN), or does it also cover NFS datastore equivalents? | High | ⬜ Unanswered |
| Q10 | Can Snapshot / SnapMirror / FlexClone / Storage Efficiency continue to be used after migration (lineage and metadata carryover)? | Critical | ✅ Confirmed |
| Q11 | Is Preview available in the supported region (Tokyo ap-northeast-1)? What are the Preview constraints and GA timeline outlook? | Medium | ⬜ Unanswered |

### Q10 Answer Basis (Official Shift Toolkit EC2 Procedure, 2026-06)

Confirmed from the procedure's migration flow:
- SnapMirror replicates from source ONTAP → FSx for ONTAP
- SnapMirror is broken at migration time, making the FSx for ONTAP side R/W
- Data disks exist as native FSx for ONTAP LUNs after VMDK → LUN conversion
- **Post-migration FSx for ONTAP operates as normal**: Snapshot / SnapMirror / FlexClone / Storage Efficiency are all natively available

**Important note**: SnapMirror is broken during migration, so the "Snapshot lineage (continuous differential chain)" with the source is severed. Post-migration, a new Snapshot policy is configured on the FSx for ONTAP side. This is by design (migration completion = cutover) and is normal expected behavior, not an issue.

## 4. Prerequisites and Operations

| # | Question | Priority | Status |
|---|----------|----------|--------|
| Q12 | Does the prerequisite "source VM must be on an ONTAP NFS datastore" also apply to the EC2 migration path? | Medium | ✅ Confirmed |
| Q13 | Does the recommended parallel conversion limit (max 10) also apply to the EC2 migration path? | Low | 🔶 Partial |
| Q14 | What is the publishable scope of Early Preview / Public Preview verification results (NDA applicability)? | Medium | ⬜ Unanswered |

### Q12–Q13 Answer Basis (Official Shift Toolkit EC2 Procedure, 2026-06)

- **Q12**: ✅ **Same prerequisite applies.** Explicitly stated in the procedure:
  > "Ensure the VM VMDKs are placed on NFSv3 volume (all VMDKs for a given VM should be part of the same volume)"
  - NFSv3 datastore only (NFSv4 is unsupported and not displayed in the UI)
  - SAN-based VMs require prior Storage vMotion to an NFS datastore

- **Q13**: 🔶 The procedure states: "Multiple VMs can be converted in parallel and the broken-off SnapMirror destination used for storing the converted VM disks accordingly." No explicit parallel limit is stated in the EC2 path documentation. The conventional 10-parallel recommendation is presumed to still apply.

## 5. DR (Disaster Recovery) Scenarios

| # | Question | Priority | Status |
|---|----------|----------|--------|
| Q15 | Is SnapMirror (continuous replication) + EC2 recovery the recommended DR architecture for VMware × ONTAP → EC2 × FSx for ONTAP? Are there other recommended patterns? | High | ⬜ Unanswered |
| Q16 | Can AWS Transform be used for DR purposes (continuous replication), or is it migration-only? (Our understanding is migration-only) | High | ⬜ Unanswered |
| Q17 | What is the recommended procedure and considerations for the recovery flow: break FSx for ONTAP destination → make R/W → iSCSI attach from EC2? | High | ⬜ Unanswered |
| Q18 | What is the recommended failback procedure (DR → on-premises resync) and expected outage window? | Medium | ⬜ Unanswered |
| Q19 | Is FlexClone the recommended approach for DR testing without breaking production replication? Are there other methods? | Medium | ⬜ Unanswered |
| Q20 | What are the architecture options and constraints for cross-region DR (FSx for ONTAP → FSx for ONTAP in another region)? | Low | ⬜ Unanswered |

> **Note**: DR scenarios are outside the scope of the Shift Toolkit v8.0 blog. Shift is a migration tool, not a DR tool. DR-related answers will be gathered through separate channels (AWS Storage Blog / NetApp Solutions documentation / SA confirmation).

---

## Notes on Confirmation Methods

- Shift Toolkit v8.0 Early Preview enablement: contact the NetApp support alias (address given in the Shift Toolkit v8.0 blog)
- Shift Toolkit download: [MySupport Shift Toolkit page](https://mysupport.netapp.com/site/tools/tool-eula/netapp-shift-toolkit) (NetApp Support account required)
- AWS Transform FSx for ONTAP destination UI: Available within the VMware migration wave planning flow (requires job creation and discovery data ingestion)

---

## Answer Summary (as of 2026-06-22 — after obtaining official procedure)

| Category | ✅ Confirmed | 🔶 Partial | ⬜ Unanswered |
|----------|-------------|-----------|--------------|
| 1. OS / Boot method | Q1, Q2, Q3, Q4 | — | — |
| 2. AWS Transform relationship | Q8 | — | Q5, Q6, Q7 |
| 3. FSx for ONTAP specs | Q10 | — | Q9, Q11 |
| 4. Prerequisites / Operations | Q12 | Q13 | Q14 |
| 5. DR scenarios | — | — | Q15–Q20 |

**Confirmed**: 8/20 questions → **Remaining unanswered (requires NetApp/AWS confirmation)**: 9/20 questions

> Note: Q1–Q4, Q8, Q10, Q12 are confirmed via the official Shift Toolkit EC2 procedure (2026-06).
> Q5–Q7 (AWS Transform relationship) and Q15–Q20 (DR) are outside Shift Toolkit scope and require confirmation through separate channels.
