# Draft feedback to AWS on FSx for ONTAP support in AWS Transform / MGN

Findings from running an AWS Transform for migrations (MGN) migration end to end in ap-northeast-1 with Amazon FSx for NetApp ONTAP as the target storage (replication → test launch → cutover → Finalize → teardown), organized into a form that can be submitted to AWS.

Every measurement cited here is documented in the [ATX FSx for ONTAP GA verification report](./atx-fsxn-ga-verification.md). This document is a submission-ready summary and adds no new claims.

## 1. Context to include when submitting

Where to file depends on the category.

| Category | Destination |
|---|---|
| Defects and error messages | AWS Support (technical support case) |
| Documentation gaps | The "Provide feedback" link on the documentation page, or a support case |
| Feature improvements | Filed as a feature request through a support case, or via the account SA |

The environment details to attach are below. **Support case numbers and vendor-internal issue IDs are not recorded in this repository.**

| Item | Value |
|---|---|
| Region | ap-northeast-1 |
| ONTAP version | 9.18.1P3D1 |
| Source | Amazon EC2 (Amazon Linux 2023, t3.small), 8 GiB boot plus two 4 GiB data disks |
| Replication method | Agent-based |
| Staging types | Boot `AUTO` (EBS), data `FSX_ONTAP` |
| Verification date | 2026-09-04 |

## 2. Items in priority order

Ordered by impact. The first three **bear directly on data integrity or migration success**.

| # | Category | Item | Impact |
|---|---|---|---|
| F1 | Defect-class | The job returns `COMPLETED` / `LAUNCHED` even when the final snapshot failed | A lost delta goes unnoticed |
| F2 | Defect-class | The job reports success for an unbootable target caused by an inconsistent disk assignment | Finalizing without noticing removes the recovery path |
| F3 | Missing capability | No way to repair an inconsistent disk assignment | Deleting and re-onboarding the source server is the only workaround |
| F4 | Documentation | The API initialization page opens as though roles are created for you, then asks you to create them in step 1 | The prerequisite is missed on the API / IaC path |
| D1 | Documentation | No statement of the resources `SETUP_FSX_PROXY` creates in the customer VPC, or their cost | Migration cost estimates do not match reality |
| D2 | Documentation | No statement that Finalize leaves the NLB and VPC endpoint service behind | Billing continues after the migration completes |
| D3 | Documentation | No statement of the physical capacity Finalize temporarily requires | Room for failure from insufficient free space |
| D4 | Documentation | No minimum ONTAP version stated, and the running version is not retrievable from the AWS API | Compatibility cannot be judged in advance |
| E1 | Error message | The hint shown when agent installation fails is unrelated to the real cause | Triage takes longer |
| E2 | Error message | Changing the staging type returns three mutually contradictory errors | The correct input cannot be inferred |

## 3. Defect-class findings

### 3.1 F1: A failed final snapshot is buried under job success

**Observed**: during cutover, `SNAPSHOT_FAIL` occurred and `USING_PREVIOUS_SNAPSHOT` fell back to the preceding snapshot, yet the job returned `COMPLETED` and the target `LAUNCHED`.

**Reproduction**: start a cutover while the replication agent is unresponsive. Here that was induced by stopping the source OS. The snapshot timed out after 300 seconds.

**Impact**: in an environment with ongoing writes, the delta covered by the fallback is lost. **The job status does not expose this risk.** It is only visible by separately reading `describe-job-log-items`.

**Why, structurally**: [`Job`](https://docs.aws.amazon.com/mgn/latest/APIReference/API_Job.html) declares `status` with Valid Values `PENDING | STARTED | COMPLETED` — there is no failure value, and per-step outcomes do not surface at that level. Failure is carried by `launchStatus` on [`ParticipatingServer`](https://docs.aws.amazon.com/mgn/latest/APIReference/API_ParticipatingServer.html) (`PENDING | IN_PROGRESS | LAUNCHED | FAILED | TERMINATED`), which covers launch only. **A snapshot fallback appears in neither field.** So `COMPLETED` is the documented response, and the request is precisely that there is nowhere for the risk to be expressed.

**Request**: when the final snapshot fails and falls back, return a warning or a non-success status at job level. At minimum, add a field to the `describe-jobs` response indicating whether a fallback occurred.

### 3.2 F2: An inconsistent disk assignment is not detected

**Observed**: a cutover ran with `FSX_ONTAP` assigned to the boot disk and `AUTO` (EBS) to a data disk, and **produced an unbootable instance** that enters a UEFI shell reboot loop. Throughout, the job returned `COMPLETED` / `LAUNCHED`.

**Reproduction**: stop and restart the source instance after agent installation so that NVMe device enumeration order changes. MGN keys the staging-type assignment on device name and does not re-evaluate it after the name moves.

**Impact**: the contents of a data disk are written to the EBS volume reserved for boot, so the target does not boot. **Because the job reports success, there is room to proceed all the way to Finalize.**

**Request**:

- Before launch, verify that no disk with `isBootDisk: true` is assigned `FSX_ONTAP`, and fail the job on a mismatch
- Detect whether the mapping between disk size and `isBootDisk` has changed since replication started
- Enable the Volume integrity validation post-launch action by default for FSx for ONTAP targets

### 3.3 F3: No route to repair an inconsistent assignment

**Observed**: `UpdateReplicationConfiguration` cannot correct the staging type in `replicatedDisks`. `isBootDisk` is not accepted as input (read-only).

**Workaround**: delete the source server and reinstall the agent. This restarts replication from the beginning.

**Request**: provide an API that re-evaluates the assignment, or an operation that syncs the stored configuration to the actual layout. If that is not feasible by design, **state in the documentation that re-onboarding is the only route**.

### 3.4 F4: The API initialization page reads as though it cancels its own prerequisite

> **Corrected 2026-09-08**: this was originally filed as a defect — reproducible CLI initialization failure. **It is not a defect.** The API path expects the customer to create 8 IAM roles first, and we had not. Withdrawn as a defect; it stays as a documentation inconsistency.

**Observed**: [Initializing AWS Transform MGN with the API](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html) opens by describing initialization as "The required IAM roles and policies will be created." Step 1 on the same page is "Create the required IAM roles", asking the customer to create 8 roles with `CreateRole` and attach their managed policies. Reading only the first sentence, `initialize-service` appears to create the roles too.

**Actual behaviour** (our own CloudTrail, us-east-1, 2026-09-03 20:31 UTC): `initialize-service` never calls `CreateRole`. It calls `CreateServiceLinkedRole` → `CreateInstanceProfile` × 4 → `AddRoleToInstanceProfile` × 4, and those last four fail with `NoSuchEntityException` (`The role with name AWSApplicationMigration...Role cannot be found.`). That matches the later text on the same page.

**Impact**: running it without meeting the prerequisite fails with `ValidationException: Failed to create SLR or instance profiles` (reason `OTHER`). The error does not name the missing role, so anyone working from the opening sentence misdiagnoses it as a service defect. **We did.**

**Request**: 1. Make the opening sentence clearly belong to the console path, since step 1 of the API path is the customer's work. 2. Include the missing role name in the `ValidationException` message.

## 4. Documentation gaps

### 4.1 D1: Resources created by `SETUP_FSX_PROXY`, and their cost

**Current state**: the official blog says a PrivateLink connection is established automatically, but **no statement was found describing what is created inside the customer VPC**.

**Measured**: an internal Network Load Balancer, a target group (TCP/443, targeting the FSx for ONTAP management endpoint IP), and a VPC endpoint service (allowed principal `mgn.amazonaws.com`).

**Request**: document the resources created, and that **NLB hourly and LCU charges are incurred in the customer account**. This is required information for a migration cost estimate.

### 4.2 D2: Resources Finalize leaves behind

**Measured**: staging and conversion EBS volumes are deleted automatically about 33 minutes after Finalize. The **NLB and VPC endpoint service were not deleted through T0 + 36 minutes**. Even after the source server was deleted, the AWS-owned VPC endpoint remained `available`.

Separately, **the target instance's root EBS volume remains even after the instance is terminated** (`DeleteOnTermination` is not set).

**Request**: document the resources that must be deleted manually after the migration completes, as a teardown procedure. Or delete them as part of Finalize.

### 4.3 D3: Physical capacity Finalize temporarily requires

**Measured**: Finalize splits the FlexClone. Before the split, the target volume's physical consumption was 35.5 MiB (7.91 GiB logical); after the split it was 8.57 GiB. Because staging-volume deletion follows about 9 minutes later, **additional physical capacity equal to one copy of the migrated data is required during that window**.

**Request**: state in Prerequisites that Finalize temporarily requires free physical capacity comparable to the migrated data size. The behaviour when free space is insufficient (does it fail, or fill the aggregate) would also be worth stating.

### 4.4 D4: Minimum ONTAP version, and how to check the running version

**Current state**: the MGN User Guide Prerequisites and Known limitations, the MGN release notes, the ATX change log, and the AWS Storage Blog article were all checked, and **no minimum ONTAP version was found** (searched 2026-09-04).

**A related gap**: the FSx for ONTAP AWS API does not return the ONTAP software version. `describe-file-systems` has no field carrying it, so checking requires reaching the ONTAP CLI or ONTAP REST API from inside the VPC. `FileSystemTypeVersion` being `None` is by design — [`FileSystem`](https://docs.aws.amazon.com/fsx/latest/APIReference/API_FileSystem.html) defines it as "The Lustre version of the Amazon FSx for Lustre file system". **The gap is that no alternative field exists.**

**Request**:

- State the minimum ONTAP version requirement. If there is none, state that explicitly
- Include the ONTAP version in the `describe-file-systems` response. If a version-dependent requirement is documented in future, **compliance cannot currently be judged from the AWS API alone**

### 4.5 Other gaps

| Item | Current state | Request |
|---|---|---|
| The additional-security-group requirement | Visible only in the console validation message and on-screen help. No corresponding statement found in the User Guide procedure | State it in the procedure |
| Post-migration mount configuration | Device paths become `/dev/mapper/<WWID>` on the target, and `/etc/fstab` is not written | State that UUID or LABEL must be used |
| Launch template on re-onboarding | Deleting and re-onboarding a source server creates a new launch template with MGN defaults, losing customizations such as the subnet | Document it |
| Choosing the secret ARN | The documentation requires the `AWSApplicationMigrationServiceManaged` tag, but the console dropdown lists every secret in the account (no tag filter) | Filter the dropdown by tag, or state that the tag is required but not used for filtering |
| Tracking Finalize progress | Finalize creates no job, so it does not appear in `describe-jobs` and its phases cannot be followed. Cleanup takes about 33 minutes | Emit a job or events. At minimum, document the expected duration |

## 5. Error message improvements

### 5.1 E1: A misleading hint when agent installation fails

**Observed**: replication agent installation failed and the installer printed "Are kernel linux headers installed correctly?". **The kernel headers were installed correctly.** The real cause was exhaustion of the build temp area (`No space left on device` / `NO_SPACE_LEFT_ON_DEVICE`).

**Background**: `/tmp` on Amazon Linux 2023 is a tmpfs sized in proportion to RAM (955 MiB on t3.small). Building the kernel module exhausted it. Pointing `TMPDIR` / `TEMP` / `TMP` at an on-disk path resolved it.

**Request**: when space exhaustion is detected, present it as the primary cause instead of the kernel-headers hint. Also state the required temp-area size in Prerequisites.

### 5.2 E2: Contradictory errors when changing the staging type

**Observed**: attempting to correct `replicatedDisks` via `UpdateReplicationConfiguration` returns one of three errors depending on input.

| Input | Error |
|---|---|
| `FSX_ONTAP` on the data disks only | `FSX_ONTAP requires FSX_ONTAP staging disk type for all volumes` |
| `FSX_ONTAP` on all disks | `InternalServerException` |
| An EBS equivalent on the boot disk | `EBS cannot use FSX_ONTAP staging disk type` |

The first says all volumes must be `FSX_ONTAP`; the third says EBS cannot use `FSX_ONTAP`. **Combined with the design in which the boot disk is always EBS, no input satisfies the first message.**

**Request**: make the validation messages consistent with the fact that the boot disk is always EBS. Treat `InternalServerException` as an input validation error.

### 5.3 Other error messages

| Observed | Current message | Request |
|---|---|---|
| Calling `start-cutover` from `TESTING` | `ConflictException` (wrong lifecycle state) | Name the required transition (`change-server-life-cycle-state` with `READY_FOR_CUTOVER`) |
| Test launch in an account with no default VPC | `VPCIdNotSpecified: No default VPC for this user` | Indicate that the MGN default launch template has no subnet set, or derive it from the staging subnet in launch settings |
| Target does not appear in SSM | `ConnectionLost` on the SSM side | Caused by the launch template carrying no IAM instance profile. Allow specifying a profile in launch settings |

## 6. Feature improvement requests

| # | Request | Basis |
|---|---|---|
| R1 | Enable the Volume integrity validation post-launch action by default for FSx for ONTAP targets | The unbootable target in F2 would have been caught right after launch |
| R2 | Pre-flight validation before replication starts (network reachability, certificate authentication, disk assignment consistency) | Most failures encountered here were detectable before starting |
| R3 | Include the ONTAP version in `describe-file-systems` | D4 |
| R4 | Key the staging-type assignment on a stable identifier (such as a serial number) rather than the device name | Device re-enumeration is the root cause of F2 |
| R5 | Emit a job or events that let Finalize progress be tracked | The durations in D2 and D3 are not knowable in advance |

## 7. What worked as expected

Improvement requests alone do not convey the whole picture, so what held is recorded too.

| Item | Measured |
|---|---|
| Certificate authentication | Works with a cluster-scope client-ca certificate and a `security login`. A negative control without the certificate returns 401 |
| Target configuration | Placed as LUNs inside a FlexVol, presented in the guest as two paths through DM-Multipath (ALUA, prio 50 / 10). XFS labels are preserved from the source |
| Data integrity | All 8 pre-recorded sha256 values matched. No difference across all 14 files |
| What the snapshot actually is | A volume Snapshot of the staging FlexVol, taking 44s for 8 GiB. A metadata operation rather than a copy |
| The Finalize split | Under 60 seconds for 7.93 GiB, and **non-disruptive**: no I/O errors and no path-down events observed |
| Teardown | Deleting from the FSx for ONTAP API side removes a FlexVol together with its LUNs, and an SVM together with its igroup and root volume |
| ONTAP version | 9.18.1P3D1 carried the path from replication through Finalize. No version-attributable failure observed |

## 8. Notes for submission

- **Always include reproduction conditions.** F1 and F2 both occur only under a particular operation order. Without the order they cannot be reproduced
- **Include the control.** F4 is only triageable because of the contrast: the CLI fails and the console succeeds
- **State that these are single measurements.** All durations and capacity figures come from one configuration measured once, and should not be submitted as general performance characteristics
- **Exclude customer names, account IDs, resource IDs, and support case numbers.** Reproduction needs the configuration, not the identifiers
