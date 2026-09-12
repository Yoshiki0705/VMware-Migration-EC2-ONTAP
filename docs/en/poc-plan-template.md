# PoC Execution Plan Template: VMware → EC2 + FSx for ONTAP Migration

> Template for partners/SIs to create customer-facing PoC plans

---

## 1. PoC Overview

| Item | Details |
|------|---------|
| Customer Name | ________________ |
| Duration | ____/__/__ – ____/__/__ |
| Business Sponsor | ________________ |
| Technical Lead (Customer) | ________________ |
| Technical Lead (Partner) | ________________ |
| Tools | □ Shift Toolkit (Early Preview) □ AWS Transform (GA) □ CMC □ MGN |
| Verification Scenario | □ Migration □ DR (Continuous Replication + Recovery) |

### The Customer's First Question

> "What comes after VMware? The optimal migration path depends on the type of storage you are currently using."

---

## 2. PoC Goals and Success Criteria

### Business Goals (Why This PoC)

| # | Goal | Details |
|---|------|---------|
| G1 | Problem to Solve | e.g., Rising VMware license costs / DR strategy / Cloud migration |
| G2 | Decision After PoC | e.g., Obtain Go/No-Go decision criteria for production migration |
| G3 | Expected Outcome | e.g., Confirm migration feasibility + cost comparison report |

### Success Criteria (Pass/Fail Criteria for the PoC)

| # | Metric | Target | Measurement Method | Go/No-Go |
|---|--------|--------|--------------------|----------|
| S1 | Data disk conversion time | ___ min or less / 100 GB | Shift Toolkit logs | Go: Met / No-Go: Not met |
| S2 | Cutover downtime | ___ min or less | Timestamp records | Go: Within tolerance |
| S3 | Data integrity | 100% | sha256sum comparison | Go: 100% required |
| S4 | Post-migration app behavior | Normal response | Application tests | Go: All tests PASS |
| S5 | Monthly cost comparison | Within ___% of current env | Cost estimate | Go: Within budget |

---

## 3. Prerequisites Checklist

### Tool and Scenario Selection

```text
■ Scenario Selection
  Migration (one-time rehost/replatform) → Proceed to tool selection flow
  DR (continuous replication + recovery)  → SnapMirror-based architecture
       * AWS Transform is migration-only. SnapMirror handles DR data replication
       * Procedure: docs/en/dr-snapmirror-runbook.md

■ Migration Tool Selection Flow
Q1: Are you currently using an ONTAP NFS datastore?
    Yes → Go to Q2
    No  → Recommend AWS MGN (out of scope for this template)

Q2: Do you want to place data disks on FSx for ONTAP (iSCSI)?
    Yes → Go to Q3
    No  → Recommend AWS MGN

Q3: How do you want to proceed with migration?
    AWS-native end-to-end (planning, compute, storage) / mixed sources
        → AWS Transform (VMware migration is free; FSx for ONTAP destination reached GA on 30 Aug 2026)
          Procedure: docs/en/aws-transform-migration-procedure.md
    Fast conversion via ONTAP FlexClone / small-to-mid scale / PoC
        → Shift Toolkit (Early Preview) ← Primary focus of this template
    100+ VMs / zero-downtime requirements
        → Cirrus Migrate Cloud (CMC)
```

### On-Premises Requirements

- [ ] VMware vCenter 7.0.3 or later
- [ ] ONTAP 9.14.1 or later
- [ ] VMs reside on NFS datastores
- [ ] Windows Server available for Shift Toolkit installation
- [ ] NetApp Support account (required to enable Early Preview)

### AWS Requirements

- [ ] AWS account (with appropriate IAM permissions)
- [ ] VPN or Direct Connect (on-premises ↔ AWS connectivity)
- [ ] Amazon FSx for NetApp ONTAP available in target region
- [ ] EC2 Key Pair created

---

## 4. Target VMs for PoC

| # | VM Name | OS | vCPU | RAM | OS Disk | Data Disk | Purpose | Priority |
|---|---------|-----|------|-----|---------|-----------|---------|----------|
| 1 | | | | | | | | High/Med/Low |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

**Selection Criteria:**

- Prioritize test VMs that do not contain production data
- Include both Linux and Windows
- Variety of data disk sizes (small/medium/large)

---

## 5. Schedule

| Week | Task | Owner | Completion Criteria |
|------|------|-------|---------------------|
| W1 | Environment setup (AWS: VPC/FSx for ONTAP/EC2) | Partner | CFn deployment complete |
| W1 | Environment setup (on-prem: Shift Toolkit install) | Customer | Shift Toolkit GUI launch confirmed |
| W2 | Connectivity verification (VPN/DX + port checks) | Both | ping/telnet successful |
| W2 | SnapMirror configuration + initial transfer | Partner | Data sync complete |
| W3 | Migration test execution (1–2 VMs) | Both | EC2 boot + data verification |
| W3 | Performance measurement | Partner | fio report generated |
| W4 | Results compilation + cost comparison + Go/No-Go decision | Both | Final report submitted |

---

## 6. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Early Preview specification changes | Procedures may require re-verification | Regular contact with NetApp; maintain separate GA-ready procedures |
| Additional steps for OS disk AMI creation | Higher-than-expected effort | Prepare VM Import/Export as a backup plan in advance |
| Insufficient VPN bandwidth | SnapMirror initial transfer delayed | Run initial transfer during off-hours; perform only incremental syncs during business hours |
| FSx for ONTAP iSCSI performance below expectations | Gap between customer expectations and reality | Increase provisioned throughput; enable Flash Cache |

---

## 7. Go/No-Go Decision

### Decision Meeting

| Item | Details |
|------|---------|
| Date | ____/__/__ |
| Participants | Business Sponsor, Technical Leads (both sides) |
| Criteria | All success criteria in Section 2 marked Go |

### Decision Outcome

| Decision | Condition | Next Action |
|----------|-----------|-------------|
| **Go** | All success criteria met | Proceed to production migration planning |
| **Conditional Go** | Some criteria not met but acceptable | Additional validation or configuration change, then re-evaluate |
| **No-Go** | Significant technical barriers | Evaluate alternative tools (CMC/MGN), or postpone |

---

## 8. Deliverables

| # | Deliverable | Author | Recipient |
|---|-------------|--------|-----------|
| 1 | PoC environment architecture diagram | Partner | Customer Technical Lead |
| 2 | Migration procedure (step-by-step) | Partner | Customer Technical Lead |
| 3 | Performance benchmark report | Partner | Customer Technical Lead + Sponsor |
| 4 | Cost comparison report (EBS vs FSx for ONTAP) | Partner | Business Sponsor |
| 5 | Go/No-Go decision document | Both | Business Sponsor |
| 6 | Production migration plan (if Go) | Partner | Customer |

---

## Appendix: CloudFormation Template

The CloudFormation template in this repository can be used to build the AWS-side PoC environment:

```bash
aws cloudformation deploy \
  --template-file templates/poc-environment.yaml \
  --stack-name shift-toolkit-poc \
  --parameter-overrides \
    VpcCidr=10.0.0.0/16 \
    FsxnThroughput=512 \
    FsxnStorageCapacity=1024 \
    Ec2KeyPairName=<your-key-pair> \
    OnPremCidr=<on-prem-cidr> \
  --capabilities CAPABILITY_IAM
```

---

*Template version: 1.0 (2026-06-03)*
*This template is a deliverable of the Shift Toolkit Early Preview verification project. Procedures may require updates after GA.*
