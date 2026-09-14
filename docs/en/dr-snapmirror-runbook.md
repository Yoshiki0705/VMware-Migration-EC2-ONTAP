# DR Runbook: On-Premises VMware × ONTAP → EC2 × FSx for ONTAP (SnapMirror-Based)

**Purpose**: Continuously replicate data from an on-premises VMware/ONTAP environment to Amazon FSx for NetApp ONTAP via SnapMirror, and recover workloads on Amazon EC2 in the event of a disaster.

> ⚠️ **Scope and Assumptions (distinction discipline)**
> - This runbook covers **DR (continuous replication + recovery)**. For one-time migration (rehost), refer to separate documents (Shift Toolkit / AWS Transform procedures).
> - **AWS Transform is a migration service and is not an orchestrator for continuous-replication-based DR.** SnapMirror handles data replication for DR. If evaluating AWS-native DR alternatives, AWS Elastic Disaster Recovery (DRS) is a candidate; however, DRS is EBS-based and differs architecturally from an FSx for ONTAP landing zone (out of scope for this runbook).
> - Numeric targets (RPO/RTO, etc.) are goals to be validated through testing and are not guaranteed values.

---

## 1. DR Architecture Overview

```text
[On-Prem Primary]                          [AWS DR Site]
VMware ESXi + ONTAP                         Amazon EC2 (standby / on-demand launch)
  data volume (NFS/LUN)                       └─ iSCSI attach
        │                                          ▲
        │ SnapMirror (Async)                       │
        └──────────────────────────────────▶ FSx for NetApp ONTAP (Multi-AZ)
                                              destination volume (break to RW for recovery)
```

- **Data replication**: ONTAP SnapMirror (Async) transfers incremental changes from on-premises ONTAP → FSx for ONTAP
- **Compute**: EC2 instances are not running during normal operations (cost minimization). On failure, launch from AMI or start a pre-created instance
- **Recovery key**: Break the FSx for ONTAP destination volume to make it RW → map LUN to igroup → iSCSI attach from EC2

---

## 2. RPO / RTO (Targets to Be Validated Through Testing)

| Metric | Definition | Target (to be validated) | Primary factors |
|--------|-----------|--------------------------|----------------|
| RPO | Acceptable data loss window | SnapMirror schedule interval (e.g., 15 min – 1 hour) | Transfer frequency, link bandwidth, change rate |
| RTO | Recovery time objective | e.g., 30–60 min (small scale) | break→RW, LUN mapping, EC2 launch, iSCSI attach, application startup |

> **Note**: The initial SnapMirror baseline transfer is not included in RPO (it is pre-DR preparation). RPO is determined by the incremental transfer interval.

---

## 3. Preparation (Normal Operations)

### 3.1 Network

- On-premises ONTAP ↔ FSx for ONTAP: Open SnapMirror ports (intercluster LIF, TCP 11104/11105) over VPN/DX
- FSx for ONTAP ↔ EC2: iSCSI (TCP 3260). See `fsxn-iscsi-setup.md` for details

### 3.2 Establishing SnapMirror Relationship (Cluster Peering → SVM Peering → Relationship Creation)

```text
# Example: Execute on the on-premises ONTAP side (source cluster)
# 1) Create cluster peer (specify FSx for ONTAP intercluster LIF)
cluster peer create -peer-addrs <fsxn-intercluster-lif> -ipspace Default

# 2) Create SVM peer
vserver peer create -vserver <onprem-svm> -peer-vserver <fsxn-svm> \
  -applications snapmirror -peer-cluster <fsxn-cluster>

# 3) Create SnapMirror relationship on the FSx for ONTAP side (destination)
snapmirror create -source-path <onprem-svm>:<src_vol> \
  -destination-path <fsxn-svm>:<dst_vol> \
  -type XDP -schedule <schedule_name>

# 4) Initial baseline transfer
snapmirror initialize -destination-path <fsxn-svm>:<dst_vol>
```

### 3.3 Continuous Monitoring of Replication Health

```text
# Check relationship state and lag
snapmirror show -destination-path <fsxn-svm>:<dst_vol> \
  -fields state,status,lag-time,last-transfer-size
```

- Periodically verify that `Healthy=true` and `lag-time` is within the RPO target
- Visualize lag via CloudWatch / monitoring (alert on threshold breach)

---

## 4. Failover Procedure (DR Activation)

```text
# 1) (If possible) Transfer a final incremental to minimize RPO
snapmirror update -destination-path <fsxn-svm>:<dst_vol>

# 2) Break the SnapMirror relationship to make the destination RW
snapmirror quiesce -destination-path <fsxn-svm>:<dst_vol>
snapmirror break  -destination-path <fsxn-svm>:<dst_vol>

# 3) Map the destination volume LUN to igroup (EC2 initiator)
lun mapping create -vserver <fsxn-svm> \
  -path /vol/<dst_vol>/<lun> -igroup <ec2-igroup> -lun-id 0
```

Then on the EC2 side:

1. Launch the DR EC2 instance (pre-created AMI, or a pre-provisioned standby instance)
2. Discover iSCSI targets, log in, and verify multipath (`fsxn-iscsi-setup.md` Steps 5-7)
3. Mount the filesystem and start the application
4. Switch DNS / load balancer to direct traffic to the DR site

> **OS / Boot handling**: EC2 cannot boot from data on FSx for ONTAP. The DR OS must be pre-built as an AMI, or launched from a golden AMI with the FSx for ONTAP data LUN attached. The same "OS = EBS / Data = FSx for ONTAP" separation principle used for migration (rehost) also applies to DR.

---

## 5. Failback Procedure (After Primary Recovery)

```text
# 1) Reverse resync (DR site → on-premises) to return the delta
snapmirror resync -source-path <fsxn-svm>:<dst_vol> \
  -destination-path <onprem-svm>:<src_vol>

# 2) Planned outage for final sync → reverse direction (re-establish resync in the forward direction)
# 3) After business resumes on-premises, re-establish forward SnapMirror
```

> Failback involves a planned outage. Document the procedure and outage window in the runbook in advance, and validate during DR tests.

---

## 6. DR Testing (Validation Without Production Disruption)

Use **FlexClone** to validate DR without breaking the SnapMirror relationship:

```text
# Create a FlexClone from the latest Snapshot on the destination (production replication continues)
volume clone create -vserver <fsxn-svm> -flexclone <dst_vol>_drtest \
  -parent-volume <dst_vol> -parent-snapshot <snapshot>

# Map the clone LUN to a test EC2 instance and verify startup
# After testing, delete the clone
volume clone ... / lun mapping delete ... / volume destroy <dst_vol>_drtest
```

- Allows measuring "can it boot, data integrity, RTO" without breaking production SnapMirror
- Conduct DR tests periodically and record results in `verification/evidence/`

---

## 7. Validation Items (DR Scenarios)

| # | Validation item | Acceptance criteria | Tool |
|---|----------------|--------------------|----- |
| D1 | SnapMirror initial transfer complete | Baseline transfer successful, Healthy=true | `snapmirror show` |
| D2 | Incremental replication lag | lag-time within RPO target | `snapmirror show -fields lag-time` |
| D3 | break → RW conversion | Destination is RW, LUN mappable | ONTAP CLI |
| D4 | EC2 launch + iSCSI attach | Launch successful, multipath active | `multipath -ll` |
| D5 | Data integrity | sha256sum match at failover point | sha256sum |
| D6 | RTO measurement | Time from break to application response | Timestamps |
| D7 | FlexClone DR test | Startup confirmed without breaking production replication | `volume clone` |
| D8 | Failback | Reverse resync successful, data return confirmed | `snapmirror resync` |
| D9 | Cross-region DR (optional) | Replication to FSx for ONTAP in another region | SnapMirror + FSx for ONTAP (DR) |

---

## 8. Teardown (undoing 3.2)

**If 3.2 created peers, teardown has to remove them.** Deleting the FSx for ONTAP stack without
removing them stalls. Measured by a sibling project on 2026-09-13 (ONTAP 9.18.1P6, ap-northeast-1;
[source](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/a97a4ec/docs/ja/verification/flexcache-security-style-inheritance.md)).

> **Remove the peers while the host is still alive.** Get the order wrong and the same stack deletion
> removes the only host that can issue the removal.

### 8.1 The correct order

```text
# 1) Release the SnapMirror relationship
snapmirror delete -destination-path <fsxn-svm>:<dest-volume>
snapmirror release -destination-path <fsxn-svm>:<dest-volume>   # on the source

# 2) Delete the SVM peer (**while the host is still alive**)
vserver peer delete -vserver <onprem-svm> -peer-vserver <fsxn-svm>

# 3) Delete the cluster peer
cluster peer delete -peer-cluster <fsxn-cluster>

# 4) Remove security group rules added by hand that reference another stack's SG
#    Left in place, they fail the referenced SG's deletion with a dependency error

# 5) Delete the stack
aws cloudformation delete-stack --stack-name <stack>
```

### 8.2 Recovering from the wrong order

**There are four stages, and the last two only appear once the order has gone wrong.**

| Stage | Symptom |
|---|---|
| 1 | With the SVM peer still present, FSx for ONTAP does not delete the SVM and the stack fails with `svmLifecycle should be DELETING, but get: MISCONFIGURED` |
| 2 | **The same stack deletion removes the only host that can run `vserver peer delete`.** The management LIF is a private address, so once the verification host is gone ONTAP is unreachable by REST and CLI alike |
| 3 | Removing the peer leaves `Lifecycle` at `MISCONFIGURED`, and **CloudFormation reads that value and refuses before calling delete** |
| 4 | Security group rules added by hand block deletion of the referenced group |

Recovery order:

```text
# 1) Rebuild a host that can reach ONTAP (a t3.micro is enough)
# 2) Remove the peers (8.1 steps 2-3)
# 3) **Delete the SVM directly through the FSx for ONTAP API.**
#    delete-storage-virtual-machine is accepted even at MISCONFIGURED and moves to DELETING
aws fsx delete-storage-virtual-machine --storage-virtual-machine-id <svm-id>
# 4) Retry the stack deletion
```

### 8.3 Whether a final backup is left behind

**It depends on the deletion path.** In the sibling project's measurements, the two volumes deleted by
CloudFormation left a final backup and the four deleted through the ONTAP REST API did not.
**Count them after teardown.**

```bash
aws fsx describe-backups --query 'Backups[].{Id:BackupId,Vol:Volume.Name,Type:Type}' --output table
```

## 9. Risks and Considerations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| SnapMirror lag exceeds RPO | Increased data loss | Shorten schedule, increase bandwidth, avoid high-change-rate windows |
| Accidental operation after break prevents resync | Failback becomes difficult | Document procedures in runbook, rehearse during DR tests |
| OS boot not prepared | RTO exceeded | Pre-create DR AMI, update regularly |
| iSCSI igroup not registered | Cannot map at recovery time | Pre-register EC2 initiator, or automate during launch |
| Cost misunderstanding | Unexpected charges | Keep EC2 stopped during normal operations. FSx for ONTAP destination capacity and transfer incur ongoing charges |

---

*This runbook is a draft for validation purposes based on SnapMirror / FSx for ONTAP official documentation (as of June 2026). Actual commands and parameters should be confirmed in the test environment before finalization.*
