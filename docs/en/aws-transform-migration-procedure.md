# Procedure: VMware → EC2 / FSx for ONTAP Migration Using AWS Transform

**Purpose**: Migration procedure for rehosting VMware workloads to Amazon EC2 using AWS Transform (an agentic AI migration service), with block data placed on Amazon FSx for NetApp ONTAP.

> ✅ **GA / 30 August 2026**. The capability to target FSx for ONTAP as a migration destination is now GA. [(Primary source: What's New)](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/) Hands-on results are in [the GA verification report](atx-fsxn-ga-verification.md). **This procedure was written during Public Preview (2026-06), so the UI and its labels may have changed since GA.** Do not treat as GA specification. Primary sources: [What's New](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/) / [AWS Transform pricing](https://aws.amazon.com/transform/pricing/)

---

## 0. Positioning

- AWS Transform is an AWS-native orchestrator that drives **the entire migration wave (discovery → planning → compute + network + storage)**.
- The VMware migration agent itself is **free to use**. Standard charges apply for destination AWS resources (EC2 / EBS / FSx for ONTAP / data transfer, etc.).
- The convergence point is the same as other approaches: **OS/root on EBS, data on FSx for ONTAP (iSCSI)** (EC2 cannot boot directly from FSx for ONTAP).

---

## 1. Prerequisites

Organized based on the official blog ([Accelerating VMware migration](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/)):

- **AWS Organizations** set up
- **AWS IAM Identity Center** set up (used for user assignment to Transform)
- AWS account structure:
  - **Migration planning account**: The account running AWS Transform (control plane)
  - **Target account**: The account where destination EC2 / FSx for ONTAP resources are placed
  - Both within the same Organization. For small-scale environments, consolidation into a single account is possible
- Authorization to use AWS Transform. Access methods:
  - **Web API authentication (SSO / IAM Identity Center or Cookie)**
  - **SigV4 (AWS credentials)**: When the account supports the Transform API
- Discovery inventory (one of the following):
  - **AWS Transform Discovery Collector OVA** (deployed to on-premises vCenter; collects information without AWS connectivity; supports SQL Server detection)
  - **RVTools** export (CSV/XLSX)
  - **NetApp DII**
  - **Migration Evaluator / MPA**
  - **PowerCLI-based collector** ([aws-samples/sample-vmware-collector-v2](https://github.com/aws-samples/sample-vmware-collector-v2); outputs in MPA/ME/RVTools format; can collect up to 365 days of performance data at P95)
- Destination FSx for ONTAP file system (Multi-AZ recommended) and SVM
- On-premises ↔ AWS network connectivity (VPN/DX)

---

## 2. Operation Methods (Two Options)

### 2A. AWS Management Console

- Start the VMware migration transformation path in the AWS Transform console.
- Ingest discovery data → dependency mapping → wave planning → select destination (EC2 / network / **FSx for ONTAP storage destination**) → execute.

### 2B. AWS Transform MCP Server (Pre-configured in This Repository)

`awslabs.aws-transform-mcp-server` is configured in `.kiro/settings/mcp.json`. Read operations are auto-approved; creation operations (`create_workspace` / `create_job`, etc.) require per-action approval.

Typical operation flow (request in natural language to AI → MCP tools execute internally):

1. Connection check: `get_status` (SigV4 availability / authentication state)
2. Agent verification: `list_resources(resource="agents", agentType="ORCHESTRATOR_AGENT")` → confirm `vmware-migration-agent-v2`
3. Workspace creation: `create_workspace` (※ resource creation — execute after approval)
4. Connector creation: `create_connector` (S3 / code source; for discovery data S3, etc.)
5. Job creation and start: `create_job` (specify the VMware migration agent as orchestratorAgent)
6. HITL task handling: `list_resources(resource="tasks")` → `get_resource(resource="task")` to review content → **after user approval** `complete_task`
7. Status check: `get_job_status` / wait for progress with `adaptive_poll`

> **Guardrails**: HITL (Human-in-the-Loop) tasks are never auto-approved (content is always presented → user decides). `create_*` / `control_job` / `complete_task` / `accept_connector` require per-action confirmation.

---

## 3. Migration Steps (Wave)

Flow based on official documentation ([UserGuide: Migrate servers](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-migrate-servers.html)) and [MGN agent automation blog](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migrations-with-aws-transform-and-mgn-replication-agent-installation-automation/):

### 3.1 Overall Workflow

```text
┌────────────────────────────────────────────────────────────────────┐
│ AWS Transform VMware Migration Workflow                             │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  [Prerequisites + Migration Defaults]                              │
│    - Target accounts / Network infra / Inventory file              │
│    - EC2 recommendation preferences                                │
│    - MGN initialization (IAM roles auto-created)                   │
│    - EC2 launch template defaults                                  │
│                                                                    │
│  [Step 1] Set up migration wave                                    │
│    - Migration mode: Single-account or Multi-account               │
│    - Resource tagging (CreatedBy: AWSTransform)                    │
│    - Networking data → inventory                                   │
│    - Replication settings + Launch template                        │
│    - IP strategy: Static (with CIDR transform) or DHCP             │
│                                                                    │
│  [Step 2] Validate and confirm inventory                           │
│    - CSV/XLSX review: server names, EC2 types, subnets, SGs        │
│    - BYOL vs License Included / Tenancy options                    │
│                                                                    │
│  [Step 3] Deploy replication agents                                │
│    - 3 methods: Org tools / MGN Connector / Manual                 │
│    - MGN Connector: Linux VM on-prem → SSH/WinRM to source VMs     │
│    - Credentials via AWS Secrets Manager                            │
│    - Per-server status tracking                                    │
│                                                                    │
│  [Step 4] Data replication                                         │
│    - Continuous block replication to AWS (EBS staging area)         │
│    - FSx for ONTAP destination: block data replicated directly     │
│      (GA 30 Aug 2026 — no intermediate storage required)           │
│                                                                    │
│  [Step 5] Testing                                                  │
│    - Test instance launch → validation                             │
│                                                                    │
│  [Step 5b] Mark ready for cutover                                  │
│    - Application-level readiness confirmation                      │
│                                                                    │
│  [Step 6] Cutover                                                  │
│    - Final sync → Instance launch → Deployment approval (HITL)     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

> **Finalize is not part of the flow above.** It is an explicit, irreversible step taken after cutover, and it is **not cleanup — it is the step where physical capacity peaks**. Splitting the FlexClone temporarily needs one extra copy of the migrated data in physical capacity (held for about 9 minutes here; see 12.10 in the [GA verification report](./atx-fsxn-ga-verification.md)). Do not run it while free space in the aggregate is below the size of the migrated data.

### 3.2 Automated Agent Deployment via MGN Connector

AWS Transform supports large-scale automated deployment of replication agents using the MGN Connector.

| Item | Details |
|------|---------|
| Connector execution environment | On-premises Linux machine (connects to source VMs via SSH/WinRM) |
| Connector → AWS communication | SSM Hybrid Activation (HTTPS 443 outbound) |
| Credential management | Stored in AWS Secrets Manager (per-server or shared) |
| Multi-account | A single Connector can target multiple accounts |
| Reuse | Reusable across waves (within Hybrid Activation validity period: 30 days) |

#### Security Requirements for Credential Management

The MGN Connector connects to source VMs, so SSH keys and passwords are stored in AWS Secrets Manager. Implement the following security measures.

| Measure | Description |
|---------|-------------|
| **Encryption key** | CMK (Customer Managed Key) recommended. AWS-managed key also works, but for production use CMK for individual rotation and access policy management |
| **Access policy** | Restrict Secret access to the MGN Connector's IAM role (`AWSApplicationMigrationConnectorManagementRole`) only. Explicitly Deny other principals via resource-based policy |
| **Rotation** | Delete or rotate the Secret after each migration wave completes. Do not leave unused Secrets indefinitely |
| **Audit** | Record `secretsmanager:GetSecretValue` callers in CloudTrail. Detect unexpected access |
| **Secret structure** | Follow the official format (see below) |

```json
{
  "WinConnectionProtocol": "HTTPS",
  "WinUserName": "<WINDOWS_USERNAME>",
  "WinPassword": "<WINDOWS_PASSWORD>",
  "LinuxUserName": "<LINUX_USERNAME>",
  "LinuxPrivateKey": "<LINUX_PRIVATE_KEY>",
  "LinuxHostKeyValidation": false
}
```

> **WinRM Security**: `WinConnectionProtocol` **must be `HTTPS`**. HTTP (port 5985) is unencrypted and risks credentials being transmitted in plaintext. Pre-configure the WinRM HTTPS listener on Windows source VMs:
>
> ```powershell
> # Enable WinRM HTTPS on source VM (self-signed certificate example)
> $cert = New-SelfSignedCertificate -DnsName $env:COMPUTERNAME -CertStoreLocation Cert:\LocalMachine\My
> winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"$env:COMPUTERNAME`"; CertificateThumbprint=`"$($cert.Thumbprint)`"}"
> # Open port 5986 in firewall (close 5985)
> New-NetFirewallRule -Name "WinRM-HTTPS" -DisplayName "WinRM HTTPS" -Protocol TCP -LocalPort 5986 -Action Allow
> ```
>
> **Production recommendation**: Use certificates issued by an internal CA instead of self-signed. Distributing WinRM HTTPS listeners via Group Policy is efficient for large-scale environments.

### 3.3 Storage Replication to FSx for ONTAP Destination

> **What's New (2026-06-16)**: "AWS Transform replicates block storage data directly to FSx for ONTAP volumes as part of the same migration wave that handles compute and network, eliminating the need for intermediate storage platforms, separate migration tools, and the additional cost and risk they introduce."

**Confirmed information:**

- Block storage data is **replicated directly** to FSx for ONTAP volumes
- No intermediate storage platform required
- Executed within the same wave as compute + network
- OS/root disk remains on EBS (same as traditional MGN)
- Data disk placement on FSx for ONTAP is handled within the same workflow

**Unconfirmed items (to be verified — see netapp-questions.md Q5, Q9):**

- Internal replication mechanism: AWS-native block copy, or leveraging SnapMirror/FlexClone?
- Storage format on FSx for ONTAP: placed as iSCSI LUN, or another format? → **To be determined during hands-on testing**
- Continuity of ONTAP features (Snapshot lineage) after migration

> **Storage note (inference regarding ONTAP lineage)**: AWS Transform uses MGN-based **block-level replication**, which is fundamentally different from ONTAP's SnapMirror (volume-level logical replication). Therefore, **data on FSx for ONTAP after migration is likely to be in a "newly created LUN/volume" state** (Snapshot history and SnapMirror relationships are not carried over). This is not a limitation but a design characteristic — after migration, setting up new Snapshot policies / SnapMirror relationships on the FSx for ONTAP side resolves any operational concerns. However, if the requirement is to "maintain the existing Snapshot chain during migration," **Shift Toolkit (SnapMirror-based) is better suited**. This will be confirmed during hands-on testing.
>
> ⚠️ **The above is an inference based on public information and is NOT confirmed. Verify the behavior during hands-on testing.**

> **Post-migration LUN placement needs a tidying step.** As measured, every data disk of one server ended up as a LUN inside a single volume (see 12.3 in the [GA verification report](./atx-fsxn-ga-verification.md)). **What that placement decides is not performance but recovery granularity**: Snapshot and SnapMirror operate per volume, so LUNs in the same volume get a mutually consistent copy from one Snapshot and cannot be reverted individually. To revert per LUN, separate them after migration with `lun move` (not run here — U5).

### 3.4 Supported Regions

AWS Transform for VMware is [available in 16 regions](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/) (as of 2026-06).

> **Tokyo region (ap-northeast-1) status**: AWS Transform for VMware's core features are available in the Tokyo region. However, **whether the FSx for ONTAP destination feature is available in Tokyo is unconfirmed**. Preview feature regional rollout is phased, so verify by checking the console or confirming via an AWS SA.
>
> **How to verify**: Log in to the AWS Transform console (https://console.aws.amazon.com/transform/) and check whether the "FSx for ONTAP" option appears in the storage destination selection when creating a VMware migration job.

---

## 4. Validation Items (AWS Transform Migration Scenario)

| # | Validation Item | Acceptance Criteria | Notes |
|---|----------------|--------------------|----|
| T1 | Discovery ingestion | RVTools/DII interpreted correctly | Record NetApp DII integration behavior |
| T2 | FSx for ONTAP destination selection UI | FSx for ONTAP can be specified as destination in wave planning | Screenshot (masked) |
| T3 | Rehosted EC2 launch | Normal boot, status check OK | OS = EBS |
| T4 | Data placement on FSx for ONTAP | Block data placed on FSx for ONTAP volume | Record iSCSI/protocol |
| T5 | Data integrity | sha256sum matches before and after migration | |
| T6 | ONTAP feature continuity | Snapshot/SnapMirror/Efficiency available | **To verify**: replication lineage continuity |
| T7 | Cutover downtime | Measured and recorded | Measurement interval: from final sync initiation (source server cutover triggered) → target EC2 status check 2/2 pass |
| T8 | Cost | Service free; itemize destination infrastructure costs | research.md 3.2.3 / Section 6 Phase 3d |

---

## 5. Unconfirmed Items Requiring Verification (NetApp / AWS)

Linked with `netapp-questions.md`. In particular:

- Does AWS Transform's FSx for ONTAP migration internally use SnapMirror/FlexClone, or AWS-native copy? (Impacts ONTAP lineage continuity post-migration)
- Is the FSx for ONTAP destination block-only (iSCSI LUN), or does it also cover NFS datastore equivalents?
- Supported regions (Preview availability in Tokyo ap-northeast-1) and constraints / GA timeline

---

## 6. Comparison and Selection Guidance: AWS Transform vs Shift Toolkit

> For details, see [`research.md` Section 3.2.3](./research.md). Below is a summary based on the latest information.

### Quick Decision Flow (Decide in 1 Minute)

```text
Q1: Are source VMs on an ONTAP NFS datastore?
├─ No → AWS Transform is the only option (Shift Toolkit requires ONTAP NFS)
│
└─ Yes
    Q2: Migration scale?
    ├─ Large (100+ VMs / multi-account / automated NW transformation needed)
    │   → Recommend AWS Transform
    │
    └─ Small-to-medium / PoC / want to leverage FlexClone's sub-second conversion
        Q3: Downtime requirement?
        ├─ Must minimize (minutes-level) → AWS Transform (continuous replication)
        └─ 30 min–2 hour planned outage acceptable → Shift Toolkit
```

> **Note**: Both tools are free. The decision is not "which is cheaper" but "which suits the environment and requirements."

### Selection Criteria

| Criterion | Choose AWS Transform when | Choose Shift Toolkit when |
|-----------|--------------------------|--------------------------|
| **Source environment** | Mixed (any VMware environment, not limited to ONTAP) | VMs on ONTAP NFS datastore |
| **Scale** | Medium to large (100+ VMs, multi-account) | Small to medium / PoC |
| **Orchestration** | End-to-end: discovery → network → compute → storage | Specialized in disk conversion + iSCSI placement |
| **Downtime** | Continuous replication → short cutover | Planned outage (SnapMirror break + conversion) |
| **Replication method** | Agent-based (MGN — continuous block-level sync) | SnapMirror (volume-level — sync completed beforehand) |
| **FSx for ONTAP placement method** | AWS-native (direct replication — internal mechanism undisclosed) | VMDK → LUN conversion (FlexClone-based, size-independent) |
| **OS disk handling** | MGN automatically handles EBS boot conversion | VMDK → RAW → S3 → AMI (or EBS Direct API) |
| **Cost (tooling)** | Free (VMware migration) | Free |
| **ONTAP operational continuity** | To be verified (SnapMirror lineage continuity unclear) | SnapMirror break → FSx for ONTAP native thereafter |
| **Network transformation** | AI auto-generated (vSwitch → VPC/SG) | Manual (Network Mapping via Blueprint) |
| **Maturity** | GA (core features) + FSx for ONTAP destination also GA (30 Aug 2026) | Early Preview |

### Combination Patterns (Not Mutually Exclusive)

```text
Pattern A: AWS Transform standalone
  discovery → planning → network → compute(EBS) + storage(FSx for ONTAP) → cutover
  → Simplest approach. Source-environment agnostic. Suited for large scale.

Pattern B: Shift Toolkit standalone
  SnapMirror pre-sync → VM shutdown → break → VMDK conversion → AMI + LUN → EC2 launch
  → FlexClone fast conversion is effective in existing ONTAP environments. Suited for small-to-medium / PoC.

Pattern C: AWS Transform (planning + network) + Shift Toolkit (storage conversion)
  Use AWS Transform for discovery + network + planning
  → Data migration via Shift Toolkit's SnapMirror + FlexClone for fast execution
  → Currently requires manual orchestration as no integrated API exists
  → Potential for automation if DII integration is expanded in the future
```

### Migration Downtime Comparison

| Aspect | AWS Transform | Shift Toolkit |
|--------|--------------|--------------|
| Replication method | Continuous block sync (agent-based) | SnapMirror (volume-level + final update) |
| Cutover downtime | Final sync only (**estimate**: minutes to ~10 min) | 30 min – 2.5 hours (dominated by S3 upload + import-image) |
| Future improvement | — | Significant reduction expected with EBS Direct API |

> **⚠️ distinction discipline**: AWS Transform's cutover time of "minutes to ~10 min" was an **unmeasured estimate at the time this procedure was written (2026-06)**. Measurements taken after GA are in [the verification report](atx-fsxn-ga-verification.md). Shift Toolkit's "30 min – 2.5 hours" is calculated from the official procedure flow (pre-validation). Both will be updated to confirmed values after hands-on testing.

### Migration Cost Structure

| Cost Element | AWS Transform | Shift Toolkit |
|-------------|--------------|--------------|
| **Tool usage fee** | Free | Free |
| **Storage during replication** | Staging EBS (target region, charged during replication period) | FSx for ONTAP (SnapMirror destination; SSD + throughput charges from replication start) |
| **S3 staging** | None | Temporary storage of boot RAW (hours to ~1 day; prorated $0.025/GB-month) |
| **Data transfer** | Source → AWS (via DX/VPN; agent-based continuous transfer) | Source ONTAP → FSx for ONTAP (SnapMirror via DX/VPN) |
| **Destination infra (ongoing)** | EC2 + EBS(boot) + FSx for ONTAP(data) | EC2 + EBS(boot) + FSx for ONTAP(data) |

> **Note**: Destination infrastructure costs are identical for both. The difference lies in staging costs **during the replication period**. AWS Transform charges for staging EBS during continuous replication (data volume × days). Shift Toolkit charges for FSx for ONTAP operating as the SnapMirror destination from the point replication is configured. At the PoC level, neither is a dominant cost (a few dollars/day).

---

## 7. Rollback Procedures

Recovery procedures for issues occurring at each stage of migration via AWS Transform (MGN). Basic principle: **the source VM continues running until migration is complete (cutover), so stopping replication + terminating test/cutover instances safely returns to the original state.**

> **Key difference from Shift Toolkit**: Shift Toolkit performs a SnapMirror break (irreversible operation) before conversion, so rollback requires resync. AWS Transform (MGN) uses continuous replication, so the source VM remains active and unmodified at all times. Rollback simply means "cleaning up AWS-side resources."

### 7.1 Rollback Decision Flow

```text
Problem detected
  │
  ├─ Step 3 (agent deployment) failure
  │   → No changes to source VM. Reinstall agent or manually remove (7.2)
  │
  ├─ Step 4 (replication) failure or lag not resolving
  │   → Stop replication. Source VM is unaffected (7.3)
  │
  ├─ Step 5 (testing) — issues found on instance
  │   → Terminate test instance. No impact to source (7.4)
  │
  └─ Step 6 (cutover) — issues found after cutover
      → Decide whether to continue with cutover instance or revert to source (7.5)
```

> **This decision flow closes the moment a client starts writing on the target**, not at cutover. After that, simply reverting to the source loses data, and synchronization in the opposite direction (failback) has to be planned separately (7.5).

### 7.2 Agent Deployment Failure

Case where the replication agent installation fails on the source VM.

```bash
# 1. Linux: Uninstall agent (if partially installed)
sudo /opt/aws-replication/bin/aws-replication-uninstall

# 2. Windows: Remove AWS Replication Agent from Add/Remove Programs
# Or PowerShell:
# Start-Process msiexec.exe -ArgumentList "/x","{PRODUCT_CODE}","/quiet" -Wait

# 3. Archive the source server in MGN console
# AWS CLI:
aws mgn update-source-server --source-server-id s-xxxxxxxxx --life-cycle '{"state":"DISCONNECTED"}'
aws mgn archive-source-server --source-server-id s-xxxxxxxxx
```

**Resolution**: Identify root cause (network / authentication / disk space) → fix → redeploy.

### 7.3 Replication Failure / Lag Not Resolving

Case where the agent is running but replication does not complete or produces errors.

```bash
# 1. Check replication state
aws mgn describe-source-servers \
  --filters '{"isArchived": false}' \
  --query "items[].{id:sourceServerID,state:dataReplicationInfo.dataReplicationState}"

# 2. Stop replication (disconnect source server)
aws mgn disconnect-from-service --source-server-id s-xxxxxxxxx

# 3. Archive source server if completely reverting
aws mgn archive-source-server --source-server-id s-xxxxxxxxx

# 4. Staging EBS / replication resources are automatically deleted
```

> **Note**: Stopping replication does not affect the source VM. The agent simply goes idle on the source VM.

### 7.4 Test Instance Issues

Case where the test-launched EC2 instance does not behave as expected.

```bash
# 1. Terminate test instance (MGN console or CLI)
# AWS Transform UI: Select "Terminate test instances" in Testing phase
# CLI:
aws mgn start-revert --source-server-id s-xxxxxxxxx

# 2. Test instance related resources (EBS volumes, ENI) are automatically cleaned up

# 3. Fix the cause (launch template / SG / IP / drivers, etc.)

# 4. Re-test
aws mgn start-test --source-server-ids s-xxxxxxxxx
```

> **Note**: Replication continues during testing. The test-failure → fix → re-test cycle can be repeated as many times as needed.

### 7.5 Rollback After Cutover

Case where a critical issue is discovered after cutover is complete and the target EC2 is running in production.

```text
Decision point:
  Q: Has new data been written to the target EC2 after cutover?
  ├─ No (immediately after cutover, production traffic not yet flowing)
  │   → Terminate target + restart source VM (no data loss)
  │
  └─ Yes (production traffic started, new data exists)
      → Simple rollback would result in data loss
      → Options:
        A) Fix the issue on the target EC2 and continue
        B) Back up new data on target → revert to source → merge data
        C) Set up reverse replication (target → source)
```

```bash
# Rollback immediately after cutover (no new data):

# 1. Terminate target EC2 instance
aws ec2 terminate-instances --instance-ids i-xxxxxxxxx

# 2. Check and delete related EBS / FSx for ONTAP resources
aws ec2 describe-volumes --filters "Name=tag:CreatedBy,Values=AWSTransform"
# Delete as needed

# 3. Check source server status in MGN
aws mgn describe-source-servers --filters '{"sourceServerIDs": ["s-xxxxxxxxx"]}'

# 4. Restart source VM (power on via VMware)
# vCenter UI or PowerCLI: Start-VM -VM <VM_NAME>

# 5. Revert DNS / load balancer (if network changes were made)
```

### 7.6 Post-Rollback Verification Items

| Verification Item | Method |
|-------------------|--------|
| Source VM running normally | vCenter UI: power state / VMware Tools heartbeat |
| Application functioning correctly | Application-specific health checks |
| Replication resources cleaned up | Confirm archived via `aws mgn describe-source-servers` |
| Unnecessary AWS resources | Check EC2 / EBS / ENI / SG resources with `CreatedBy: AWSTransform` tag |
| Cost accrual stopped | Confirm staging EBS deleted (automatic after replication stops) |

### 7.7 AWS Transform vs Shift Toolkit — Rollback Characteristics Comparison

| Aspect | AWS Transform (MGN) | Shift Toolkit |
|--------|---------------------|---------------|
| Source VM state | Always running (no changes during replication) | Shut down at cutover → SnapMirror break |
| Essence of rollback | Deletion of AWS-side resources only | SnapMirror resync + intermediate file deletion |
| Point of no return | When new data is written after cutover | At SnapMirror break (recoverable via resync, but requires delta transfer) |
| Rollback time | Immediate (terminate + archive) | 10–30 min (waiting for resync) |
| Risk level | Low (source is non-destructive) | Medium (incorrect resync direction can overwrite source) |

---

*This procedure is a verification draft written during Public Preview (as of 2026-06). The FSx for ONTAP destination reached GA on 30 August 2026; measurements taken after GA are in [the verification report](atx-fsxn-ga-verification.md).*

---

## 8. Verification Results (2026-06)

### 8.1 AWS Transform Console Findings

Operated the AWS Transform console (Tokyo region: ap-northeast-1) on 2026-06-25 and confirmed:

| Item | Finding |
|------|---------|
| VMware Migration feature | **Production-ready (not Preview)**. UI explicitly states: "VMware migration to EC2 is not a preview feature; it is a production-ready capability" |
| UI | Chat-based (Agentic AI). Migration operations can be directed in natural language |
| Workspace creation | `VMware-Migration-Test01` created (request → available within minutes) |
| Migration process | Explained in 4 steps: 1. Assessment → 2. Planning → 3. Execution → 4. Validation |
| Job creation | VMware Migration jobs can be created to begin assessment and planning phases |

> **Important correction**: AWS Transform's VMware → EC2 migration is a **production feature (GA)**. The FSx for ONTAP destination for storage migration also reached GA on 30 August 2026. Since the former MGN (Application Migration Service) was integrated and evolved into Transform, EBS-target rehosting is a mature capability with a long history.

### 8.2 AWS Transform and Former MGN Relationship

| Aspect | Description |
|--------|-------------|
| Name evolution | AWS Server Migration Service → AWS MGN (Application Migration Service) → **Integrated into AWS Transform** |
| EBS-target migration | Mature feature existing since the MGN era. Production-ready |
| FSx for ONTAP-target migration | Added as Public Preview in 2026-06; GA on 30 Aug 2026 |
| UI/UX | Evolved from traditional console → **Agentic AI (chat-based)**. Job creation and management via conversational interface |

### 8.3 Current Constraints / Items Under Investigation

- After workspace creation, there may be a time lag before job creation becomes available ("Request has been initiated" display)
- Tokyo region availability of FSx for ONTAP destination feature continues to be investigated
- vCenter connection information preparation is required (used in Discovery phase)

### 8.4 Next Steps

- [ ] Create VMware Migration job and start assessment phase
- [ ] Input vCenter connection information and execute Discovery
- [ ] Confirm availability of FSx for ONTAP destination option
- [ ] Execute test migration (boot disk only → EBS) and measure actual downtime

---

## Reference Links

- [AWS Transform VMware — Migrate servers (UserGuide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-vmware-migrate-servers.html)
- [AWS Transform VMware migration overview (UserGuide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-app-vmware.html)
- [AWS Transform now supports FSx for ONTAP (What's New, 2026-06-16)](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/)
- [Accelerating VMware migration: AWS Transform's new experience](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/) — E2E walkthrough
- [Accelerating VMware Cloud Migration with PowerCLI](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-cloud-migration-with-aws-transform-and-powercli/) — PowerCLI collector
- [MGN replication agent installation automation](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migrations-with-aws-transform-and-mgn-replication-agent-installation-automation/) — Large-scale agent deployment
- [Network Migration APIs](https://aws.amazon.com/blogs/migration-and-modernization/automate-large-scale-network-migration-using-aws-transform-network-migration-apis/) — Network transformation API
- [Guidance for Automated Setup of AWS Transform for VMware](https://aws.amazon.com/solutions/guidance/automated-setup-of-aws-transform-for-vmware/) — Automated test environment setup (2026-06)
- [AWS Transform top page (NY Summit 2026 announcements)](https://aws.amazon.com/transform/) — storage migration / continuous modernization
- [AWS Transform pricing](https://aws.amazon.com/transform/pricing/)
- [AWS Transform FAQ](https://aws.amazon.com/transform/faq/)
- [Modernize VMware workloads with agentic AI](https://aws.amazon.com/transform/vmware/)
- [Migrate VMware to Amazon EC2 & iSCSI-based FSx for ONTAP (NetApp Blog)](https://www.netapp.com/blog/aws-fsxn-blg-migrate-vmware-to-amazon-ec2-iscsi-based-fsx-for-ontap/)
- [aws-samples/sample-vmware-collector-v2](https://github.com/aws-samples/sample-vmware-collector-v2) — PowerCLI inventory collection tool
- [Shift Toolkit EC2 migration procedure (this repository)](./shift-toolkit-ec2-procedure.md) — comparison reference
