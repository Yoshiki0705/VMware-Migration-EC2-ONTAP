# AWS Transform FSx for ONTAP Support GA — Verification Report

**Purpose**: Establish the scope of Amazon FSx for NetApp ONTAP support GA in AWS Transform (ATX) from primary sources, and record hands-on findings from a verification account (ap-northeast-1) with verified and unverified claims kept separate.

**Last Updated**: 2026-09-04
**Status**: Measured from scope confirmation through initialization, certificate authentication, saving the configuration, running replication, launching a test instance, and checking data integrity, and **Finalize was run with approval** (12.10). Teardown complete (Section 13)

---

## 1. Conclusion

What reached GA is **the ability to select FSx for ONTAP as a target storage type in AWS Transform for migrations (MGN)**. It is not a capability that presents FSx for ONTAP as a VMware **datastore**. These are two separate paths, and conflating them leads to incorrect design decisions.

| Question | Answer | Tag |
|---|---|---|
| Can FSx for ONTAP be selected as a server migration target in ATX/MGN? | Yes. `FSX_ONTAP` was set on a replication template and confirmed persisted on read-back | Measured |
| Is FSx for ONTAP presented as a **datastore** in the VMware modernize path? | No. Datastore use is a separate capability on the Amazon EVS side | Documented |
| Which disks are migrated? | Data volumes only. **The boot volume always remains on EBS** | Documented |
| What connection protocol is used? | iSCSI. Placed as LUNs inside a FlexVol and presented in the guest through DM-Multipath (ALUA) | Measured |
| Can EC2/EBS be the source? | **Yes.** An EC2 (Amazon Linux 2023) source was taken through replication, test launch, and cutover with data integrity matching | Measured |
| Is ONTAP 9.20.1 a requirement? | No minimum ONTAP version appears in public documentation. **The path held from replication through cutover on 9.18.1P3D1** (measured) | Measured |

**Discrepancy in the GA date**: The AWS Transform User Guide Change log and Document history both state **2026-08-30**, and the MGN Release notes state **August 2026**. The What's New URL, however, is under `/2026/09/`. This report treats 2026-08-30 as the availability date and 2026-09 as the announcement.

---

## 2. Evidence Tag Definitions

Every statement in this report carries one of the following tags. The mapping to the evidence tiers used in the sibling repository [FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) is given alongside.

| Tag | Meaning | Playbook tier |
|---|---|---|
| **[Measured]** | Actually executed and confirmed in this verification environment. Execution date, Region, and account type stated | `verified` |
| **[Documented]** | Stated in official AWS documentation. Source URL given. **Does not imply the behaviour was confirmed on real hardware** | `documented` |
| **[Unverified]** | Not executed, and not corroborated by public sources either. Search date and search scope stated | Body text, not a tier |

"No statement found in public documentation" is a fact about the state of the documentation, not a claim about how the product behaves. For that reason, every [Unverified] item states **when and where the search was performed**.

---

## 3. Confirming the GA Scope

### 3.1 What reached GA [Documented]

The What's New wording is "general availability of Amazon FSx for NetApp ONTAP support **as a storage target for block storage workloads** using AWS Transform for migrations" (source: [What's New 2026-09](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)).

The Change log describes it as a "generally available block storage target" alongside EBS (source: [ATX Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html)).

The GA scope is therefore the path that replicates block storage directly to FSx for ONTAP within the same migration wave that handles compute and network. The difference from previous behaviour is that no intermediate storage or separate tooling sits in between.

### 3.2 Distinguishing this from the datastore path [Documented]

The capability to use FSx for ONTAP as a VMware datastore lives in **Amazon EVS** and is unrelated to this ATX GA.

| Path | Service | Role of FSx for ONTAP | How it is reached | Status |
|---|---|---|---|---|
| Rehost (to EC2) | AWS Transform for migrations (MGN) | Target storage for data volumes | iSCSI from the guest OS | **GA** (2026-08-30) |
| Keep running VMware | Amazon EVS | External datastore (NFS v3 / v4.1 / NVMe / iSCSI VMFS) | Mounted by ESXi | Public Preview |

The capabilities validated on the EVS side are listed in the [EVS User Guide](https://docs.aws.amazon.com/evs/latest/userguide/fsx-ontap.html). No GA announcement was found as of 2026-09-04, and the most recent What's New located ([2025-06](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-elastic-vmware-service-fsx-netapp-ontap/)) states public preview. **The EVS-side status is treated as [Unverified]**.

### 3.3 Regional availability

- ATX workspace-capable Regions include Asia Pacific (Tokyo) [Documented] ([Supported Regions](https://docs.aws.amazon.com/transform/latest/userguide/regions.html))
- MGN supports ap-northeast-1 [Documented] ([What Is AWS Transform MGN?](https://docs.aws.amazon.com/mgn/latest/ug/what-is-mgn.html))
- The FSx for ONTAP target is available in "all Regions where both MGN and FSx for ONTAP are available". **Local Zones are excluded** [Documented]
- Confirmed via the Regional availability API that both services are available in ap-northeast-1 [Measured / 2026-09-04]

---

## 4. API-Level Verification

No console screenshots were captured (reasons in 5.2). What follows is an API-model-level confirmation, which is more reproducible.

### 4.1 MGN API model inspection [Measured / 2026-09-04]

Inspecting the MGN service model bundled with botocore (apiVersion `2020-02-26`) confirms that FSx for ONTAP support is present in the API contract.

```
StorageType (enum)                = ['EBS', 'FSX_ONTAP']
StorageConfiguration.storageType  -> StorageType
StorageConfiguration.fsxOntapConfiguration -> FsxOntapConfiguration
FsxOntapConfiguration (required)  = storageVirtualMachineId, credentialsSecretArn
```

Reproduction:

```bash
python3 -c "
import botocore, os, glob, gzip, json
base = os.path.dirname(botocore.__file__)
path = glob.glob(os.path.join(base, 'data', 'mgn', '*', 'service-2.json*'))[0]
with gzip.open(path, 'rt') as f:
    model = json.load(f)
print(model['shapes']['StorageType']['enum'])
print(model['shapes']['FsxOntapConfiguration'])
"
```

### 4.2 Operations that expose the capability [Measured / 2026-09-04]

Five operations carry `StorageConfiguration` in their input or output. This means the setting can be specified both on the replication template (account-wide default) and in per-server replication settings.

| Operation | Input/Output |
|---|---|
| `CreateReplicationConfigurationTemplate` | Input, output |
| `UpdateReplicationConfigurationTemplate` | Input, output |
| `DescribeReplicationConfigurationTemplates` | Output |
| `UpdateReplicationConfiguration` | Input, output |
| `GetReplicationConfiguration` | Output |

### 4.3 Supporting elements added alongside [Measured / 2026-09-04]

Elements were also added to the replication lifecycle. These are useful when triaging failures.

| Kind | Value | What it indicates |
|---|---|---|
| Initiation step | `SETUP_FSX_PROXY` | A stage exists in which ATX automatically configures the path to reach FSx |
| Error | `FAILED_TO_SETUP_FSX_PROXY` | Failure of the above stage. Suspect network or permissions |
| Error | `FAILED_TO_CREATE_FSX_SNAPSHOT` | Failure creating a snapshot on the ONTAP side |
| Staging disk type | `FSX_ONTAP` | A framework exists for specifying the staging target per disk |
| Health check type | `EC2`, `FSx` | A liveness check targeting FSx has been added |

The official blog states that this path automatically establishes a PrivateLink connection [Documented] ([AWS Storage Blog](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)). `SETUP_FSX_PROXY` above is plausibly that step, but the correspondence itself is [Unverified].

### 4.4 Target selectability and asymmetric input validation [Measured / 2026-09-04]

Beyond confirming the API model, `FSX_ONTAP` was actually set on a replication template. Template creation and update succeed even while `initialize-service` is failing (5.4).

Observed behaviour:

| # | Operation | Result |
|---|---|---|
| 1 | `create-replication-configuration-template` with `storageType=EBS` | Success. Template created |
| 2 | `update-replication-configuration-template` with `storageType=FSX_ONTAP` + a real SVM ID + a **non-existent secret ARN** | **Success.** No error |
| 3 | Read back via `describe-replication-configuration-templates` | Confirmed `FSX_ONTAP` and `fsxOntapConfiguration` are **persisted** (not merely echoed in the response) |
| 4 | `storageVirtualMachineId` set to a non-existent SVM ID | **Failure.** `ResourceNotFoundException` (`resourceType: Storage Virtual Machine`) |

**Input validation is asymmetric.** The SVM ID is checked for existence at configuration time, but `credentialsSecretArn` is not. A non-existent secret ARN is accepted and persisted.

The operational implication is that **a wrong secret ARN does not surface at configuration time**. The error is carried forward to the start of replication, where it plausibly appears as `FAILED_TO_SETUP_FSX_PROXY` (4.3). That correspondence is itself [Unverified], but a successful configuration API call must not be treated as evidence that the FSx for ONTAP integration works.

The template was deleted afterwards. Leaving a template carrying a bogus secret ARN in a shared account would hand it to the next user as their default.

### 4.5 Findings from the console UI [Measured / 2026-09-04]

> **Correction**: the first version of this section recorded that the Secret ARN dropdown offers only tagged secrets. That was wrong. It **enumerates every secret in the Region (23 of them) with no filtering**. The list appeared empty while only one tagged secret existed because it was observed before the dropdown had loaded, not because of a filter. Inferring a rule from an empty render was the error.

The console steps and screens are split out into the [MGN console procedure](./atx-fsxn-console-procedure.md). Recorded here are only the points that matter as differences from the API.

| # | Item | Result |
|---|---|---|
| 1 | Target storage selection UI | `Storage configuration` presents two tiles, `EBS` and `Amazon FSx for NetApp ONTAP` |
| 2 | Explicit statement about the boot disk | Selecting FSx for ONTAP displays "Data disks will be migrated to FSx for ONTAP. Boot disk is always migrated to EBS as required by Amazon EC2." The EBS label also changes to "EBS volume type (for boot disk)" |
| 3 | SVM enumeration | Enumerates 9 SVMs across both file systems in the Region. No filtering by AD-join status |
| 4 | Secret ARN candidates | **No filtering.** All 23 secrets in the Region are listed, including untagged ones |
| 5 | Required-field validation | Saving with the fields blank is rejected on three: SVM ID, Secret ARN, and **additional security groups** |

**Validation strength differs between the console and the API.** As noted in 4.4, the API accepts a non-existent secret ARN, whereas the console rejects on all three required fields. Furthermore, that additional security groups become required is not evident from the procedure text in the MGN User Guide; it surfaces only in the console.

When configuring through IaC or the CLI, **the existence and contents of the secret ARN must be validated yourself**. A successful configuration API call is not evidence that the integration works. The console validates whether the required fields are populated, but **not the secret's tag or its contents** (see the correction in 4.5).

### 4.6 Saving the configuration and certificate authentication [Measured / 2026-09-04]

With the three required fields satisfied, the template was saved and persistence confirmed by API read-back. The steps are in the [MGN console procedure](./atx-fsxn-console-procedure.md).

| Item | Result |
|---|---|
| `storageType` | `FSX_ONTAP` |
| `storageVirtualMachineId` | Resolves to the SVM created for this verification |
| `credentialsSecretArn` | Resolves to the secret that was created |
| Certificate authentication, with the certificate | HTTP 200, cluster information returned |
| Certificate authentication, without it (negative control) | HTTP 401 |
| ONTAP version | NetApp Release 9.18.1P3D1 |

**The ONTAP version is not obtainable from the AWS API** (7.2). The value above came from the ONTAP REST API reached through an SSM port-forward. Configuration and certificate authentication both succeeded on 9.18.1P3D1. Whether replication surfaces a different version requirement is unverified.

The certificate was installed on the **admin vserver (cluster scope)**. The created SVM does have its own management LIF, so SVM scope might suffice, but that is untested (U14).

Note that FSx pre-installs two cluster-scope client-ca certificates (`FSxCAforONTAP-1in<region>` and `AmazonFSxRootCA1for<region>`). A self-installed certificate coexists with those.

At the point of rejection the template was unchanged (`storageConfiguration` remained `null`), confirming that a validation failure performs no write. The form was then cancelled, leaving the default as `EBS`.

---

## 5. Verification Environment State and Hands-On Blockers

### 5.1 Environment state [Measured / 2026-09-04, ap-northeast-1]

| Item | State |
|---|---|
| MGN | Not initialized. `initialize-service` fails because the IAM roles do not exist yet (5.4) |
| FSx for ONTAP file systems | 2, both `AVAILABLE`, in separate VPCs |
| File system configuration | Both `SINGLE_AZ_1` / 1024 GiB / 128 MBps |
| SVMs | 9, all `CREATED`. 3 of them are AD-joined |
| Reachability to the ONTAP management endpoint | Reachable from an SSM-managed Linux host inside the VPC (HTTP 401 = TLS established, credentials required) |

**Correction about the nature of the account**: this account was initially described as a "personal verification account". It is in fact a **shared account hosting several concurrent verification workstreams**. There are 14 EC2 instances, and the candidate file system carries 6 SVMs and 25 volumes supporting unrelated work on FPolicy, SnapMirror, S3 access points, audit logging, and analytics. This affects how hands-on verification should be designed (5.3).

Both existing file systems are Single-AZ, so the Multi-AZ-specific requirement (the endpoint IP range constraint in 9.2) does not currently apply.

### 5.2 Capturing and redacting screenshots

The request included screenshot-backed records. None were captured in this session, for two reasons.

Initially no authenticated browser session was available, and MGN was uninitialized so the UI did not exist to capture. After authenticating through the browser and succeeding at console initialization, **screenshots have now been captured**.

| Location | Contents | git |
|---|---|---|
| `verification/screenshots/raw/` | Raw images | Excluded by `.gitignore` |
| `verification/screenshots/masked/` | Account ID, IAM user name, resource IDs, and internal names replaced (11 images) | Committed |

Redaction was verified with OCR, checking in pairs that **a string readable in the raw image is no longer readable after redaction** (the control held for 8 of 9 images; the remaining one is dark-theme, where OCR cannot read body text and so no control is possible, leaving the guarantee resting on the string being absent from the DOM at capture time). The steps and screens are collected in the [MGN console procedure](./atx-fsxn-console-procedure.md).

The path to reach that console screen is below. **MGN initialization is a prerequisite.**

```
MGN console -> Settings -> Replication template -> Edit
  -> Select "AWS FSx for ONTAP" as Target storage type
  -> Select Storage Virtual Machine (SVM) ID
  -> Enter FSx Storage Secret ARN
```

Source: [FSx for ONTAP configuration — Step 5](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html)

### 5.3 Work required for hands-on testing, and why approval is needed

End-to-end verification requires the following, several items of which make persistent changes to the account. Approval will be requested per item before execution.

| # | Work | Impact |
|---|---|---|
| 1 | Initialize MGN | Creates AWS managed IAM roles. Account-level state change |
| 2 | Create two security groups (cross-referencing) | New resources |
| 3 | Generate client certificate, install on ONTAP, create `security login` | Configuration change on the ONTAP side |
| 4 | Create Secrets Manager secret | New resource. Stores certificate and private key |
| 5 | Update replication template | Changes an account-wide default |
| 6 | Install agent on a source server and replicate | Requires a separate source server. Incurs transfer and staging cost |
| 7 | Test launch -> cutover -> **Finalize** | **Finalize is irreversible** (see 9.1) |

Item 1 currently fails (5.4), and items 6 onward have not been started. Items 3 and 6 onward also carry constraints specific to a shared environment.

**Reachability for the certificate install (3)**: the ONTAP management endpoint is reachable from an SSM-managed Linux host inside the VPC, but that instance profile lacks `secretsmanager:GetSecretValue`, so the fsxadmin credentials cannot be retrieved. Passing the credentials through SSM command parameters would leave them in plaintext in command history, which is not acceptable in a shared account. Either an IAM grant or an agreed alternative credential path is needed.

The fsxadmin secret description also warns that the secrets for the two file systems share a username, so attempting one against the wrong file system produces authentication failures on the real account (authentication already broke and was reset once previously). No trial-and-error probing was performed.

**Blast radius of replication (6 onward)**: running a migration requires disabling automatic backups and ARP (8.3), and both are **file-system-scope settings**. The candidate file system hosts 25 volumes belonging to other workstreams, so disabling them would extend to the data protection of that work. In addition, the capacity guidance is 3x the migration data with SSD utilization at or below 80%, and roughly 1,166 GiB is already thin-provisioned against a 1024 GiB file system, so actual usage must be established first.

### 5.4 The prerequisite initialize-service needs [Measured / 2026-09-04, corrected 2026-09-08]

> **Correction**: this section originally recorded a reproducible CLI initialization failure as a defect. **It is not a defect — it was our procedural error.** The API path expects the customer to create 8 IAM roles first, which is step 1 of [Initializing AWS Transform MGN with the API](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html). `initialize-service` creates the service-linked role, creates instance profiles and attaches **existing** roles to them; it does not create the roles. The original observations are kept below, with the basis for the correction at the end.

MGN initialization fails reproducibly.

```
$ aws mgn initialize-service --region ap-northeast-1
ValidationException: Failed to create SLR or instance profiles
Additional error details:
  reason: OTHER
```

State left behind by the failure:

| Resource | Result |
|---|---|
| Service-linked role `AWSServiceRoleForApplicationMigrationService` | **Created** |
| 4 instance profiles (ReplicationServer / ConversionServer / LaunchInstanceWithDrs / LaunchInstanceWithSsm) | **Created, but empty with no role attached** |
| The 4 corresponding IAM roles | **Not created** |

Deleting the empty instance profiles and re-running reproduces the same state. The empty profiles are therefore a symptom rather than the cause: **the role-creation stage is what fails**.

Factors ruled out during triage:

| Factor | Finding |
|---|---|
| Insufficient caller permissions | The caller holds `AdministratorAccess` |
| SCP denial | This is the Organizations management account, and SCPs do not apply to it |
| IAM quota exhaustion | 452 / 1000 roles, 40 / 1000 instance profiles |
| Name collision with existing resources | No roles of those names exist |
| IAM errors in CloudTrail | ~~No IAM events for that window appear in either region~~ → **this check was wrong.** They are in us-east-1 (see the correction below). The lookup at the time most likely used the wrong window: CloudTrail renders timestamps in local time while `--start-time` / `--end-time` are read as UTC |

Agent-based replication requires these instance profiles and roles, so **E2E verification cannot proceed until this failure is resolved**. Template configuration (4.4) does not require initialization, which is why it could be measured.

**The console path succeeds** [Measured / 2026-09-04]. Opening `Settings → Replication template` redirects to the setup screen, and choosing `Set up service` completed initialization. This was with the same credentials and the same Region as the failing CLI call.

Initialization created 9 roles, including every one the CLI path failed to create. Two of them are dedicated roles added for FSx for ONTAP support.

| Role | Managed policy | What it indicates |
|---|---|---|
| `AWSApplicationMigrationFsxProxyRole` | `AWSApplicationMigrationFSxProxyPolicy` | The path to reach FSx |
| `AWSApplicationMigrationFsxProxyLinkRole` | `AWSApplicationMigrationFSxProxyVPCPolicy` | The VPC-side connection. By name and permissions this plausibly corresponds to `SETUP_FSX_PROXY` in 4.3 and to the automatic PrivateLink establishment described in the official blog |

The presence of these two roles shows that FSx for ONTAP support is reflected in the role set at initialization time. That explains why environments initialized before FSx for ONTAP support existed need `Reinitialize Service Permissions` on the template page.

#### The basis for the correction [Measured / 2026-09-08]

CloudTrail in us-east-1 — IAM is a global service, so its events land there — shows the call sequence at the time of the failure.

| Path | `CreateRole` calls | Sequence observed |
|---|---|---|
| CLI (2026-09-03 20:31 UTC, failed) | **0** | `CreateServiceLinkedRole` → `CreateInstanceProfile` × 4 → `AddRoleToInstanceProfile` × 4, all four with `NoSuchEntityException` (`The role with name AWSApplicationMigration...Role cannot be found.`) |
| Console (2026-09-04 06:13 UTC, succeeded) | **8** | Roles created, then attached to the profiles |

`initialize-service` never attempts to create a role. It fails attaching roles that do not exist, which matches [the API initialization page](https://docs.aws.amazon.com/mgn/latest/ug/mgn-initialize-api.html):

> Once the policies are attached to the roles, run the `aws mgn initialize-service` command. This will automatically create the service-linked role, create instance profiles, and add Roles to Instance Profiles.

**The correct sequence** for the API / IaC path:

1. Create the 8 roles with `CreateRole` and attach the managed policies the page lists. With FSx for ONTAP as the target, `AWSApplicationMigrationFsxProxyRole` and `AWSApplicationMigrationFsxProxyLinkRole` are among those 8
2. `aws mgn initialize-service`
3. `aws mgn create-replication-configuration-template` and `aws mgn create-launch-configuration-template`

**Re-verification**: with the roles in place, `aws mgn initialize-service --region ap-northeast-1` succeeds (exit 0, measured 2026-09-08). **That re-run has no control**, though: reproducing the failing condition would mean deleting the roles and breaking a live verification environment, so it was not done. The evidence is the CloudTrail record above, not the successful re-run.

**Implication**: reading this as a CLI defect or an account-side problem would be a mistake. **The prerequisite for the API path is documented and we had not met it.** The console path succeeded because the console creates the roles on your behalf.

> **An inconsistency that remains in the documentation**: the same page opens by describing initialization as "The required IAM roles and policies will be created." Read together with step 1, which asks the customer to create them, that invites the misreading on the API path. It stays as F4.

---

### 5.5 Scoping the blast radius [Documented + Measured / 2026-09-04]

How much of a shared file system can be isolated differs per item. Creating a dedicated SVM helps with three of the four.

| Item | Scope | Isolated by a dedicated SVM? | Basis |
|---|---|---|---|
| Volumes / LUNs / igroups created by MGN | SVM | Yes | 8.1 |
| ARP | Per volume, or as an SVM default | Yes | `security anti-ransomware volume enable -volume X -vserver Y` / `vserver modify -anti-ransomware-default-volume-state` ([documented](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/enable-ARP.html)) |
| Automatic backups | **File system, applying to all volumes** | No | "Automatic daily backups... are file system settings, and apply to all volumes on your file system". **Setting retention to 0 also deletes the existing automatic backups** ([documented](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-backups.html)) |
| client-ca certificate + `security login` | Admin vserver (cluster) | No | The official procedure's `vserver_name` is in file-system-ID form. Additive and reversible |

**In this verification environment automatic backups are already disabled**, confirmed by finding zero backups and no AWS Backup plan targeting FSx. The backup constraint therefore does not apply here. It has to be rechecked when carrying this to another environment.

### 5.6 The SVM limit scales with throughput capacity [Measured + Documented / 2026-09-04]

An attempt to create the dedicated SVM on the file system that already had 6 SVMs failed with `ServiceLimitExceeded` (`STORAGE_VIRTUAL_MACHINES_PER_FILE_SYSTEM`). **The SVM limit is tied to throughput capacity.**

| Throughput (1 HA pair) | Maximum SVMs (IPv4) |
|---|---|
| 128 / 256 / 384 | 6 |
| **512** | **14** |
| **768** | **6** |
| 1,024 | 14 |
| 2,048 | 24 |

Source: [Managing FSx for ONTAP storage virtual machines](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-svms.html)

The limit at 768 MBps is lower than at 512 MBps, so the progression is **not monotonic**. Adding an SVM to a file system already at the limit on 128 MBps requires going to 512 MBps, and since throughput is a billable dimension that is a cost decision on a shared file system.

This verification therefore used a different file system with SVM headroom and fewer co-tenants. Its free space was 861.8 GiB in the aggregate against 50.0 GiB used (5.8% utilization), comfortably under the 80% guideline.

For E2E verification in another environment, a **dedicated file system** bounds the blast radius more cleanly.

## 6. Feasibility of Migrating from an EC2/EBS Source

### 6.1 Feasibility per documentation [Documented]

Amazon EC2 is included among MGN source types. The AWS Architecture Blog states that migration is supported from physical infrastructure, VMware vSphere, Microsoft Hyper-V, **Amazon EC2**, and Amazon VPC (source: [Multi-Region Migration using AWS Application Migration Service](https://aws.amazon.com/blogs/architecture/multi-region-migration-using-aws-application-migration-service/)).

The constraint on the FSx for ONTAP target is **agent-based replication only** [Documented]. Because EC2 sources are handled with agent-based replication, "migrating from an EC2/EBS source to EC2 + FSx for ONTAP" holds per documentation.

### 6.2 Feasibility on real hardware [Measured]

**It holds.** An Amazon Linux 2023 EC2 instance (8 GiB boot plus two 4 GiB data disks) was taken as the source through replication, test launch, and cutover, with data integrity matching (Section 12).

| Item previously unverified in 6.2 | Current status |
|---|---|
| Elapsed times (initial sync, cutover) | **Measured** (12.1, 12.9) |
| Real behaviour of LUN / volume conversion | **Measured** (12.3, 12.9) |
| Time taken for FlexClone creation | **Measured**; included in the 337s LAUNCH phase (12.9) |
| Time taken for the split at Finalize | **Measured**; starts about 3 minutes in and finishes in under 60s (7.93 GiB, 12.10) |
| EC2-source-specific pitfalls | **Two found**: `/tmp` tmpfs exhaustion (12.5) and assignment inversion from NVMe device re-enumeration (12.8) |

### 6.3 Absence of a blocker

To the question "if an EC2/EBS source is not possible, which capability is it waiting on" — the answer is that it is **not waiting on a capability**. No functional gate was found in the documentation, and on real hardware the path held through cutover on ONTAP 9.18.1P3D1. The only blocker was the MGN CLI initialization failure (5.4), resolved via the console path.

---

## 7. Handling of the ONTAP Version Requirement

### 7.1 Result of searching public documentation [Unverified]

As of 2026-09-04, the following were searched for a minimum ONTAP version and **none was found**.

- [FSx for ONTAP configuration (MGN User Guide)](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html) — Prerequisites and Known limitations
- [MGN Release notes](https://docs.aws.amazon.com/mgn/latest/ug/mgn-release-notes.html)
- [ATX Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html)
- [The explanatory AWS Storage Blog post](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)

The Prerequisites list only the MGN initialization state, VPC configuration and IPv4 reachability, and outbound reachability to OS package repositories. There is no mention of an ONTAP version.

The internally circulated "9.20.1 target" therefore **cannot be corroborated from public sources** and is excluded from the conclusions of this report.

On real hardware, **the path held from replication through cutover on ONTAP 9.18.1P3D1** (Section 12). No version-attributable failure was observed. That is one measurement on one version, and does not establish a lower bound.

### 7.2 How to check the running version [Measured / 2026-09-04]

A related finding: **the FSx AWS API does not return the ONTAP software version.** The `describe-file-systems` response contains no field indicating a version (`FileSystemTypeVersion` is `None` for ONTAP, and no corresponding field exists under `OntapConfiguration`). That is documented behaviour: [`FileSystem`](https://docs.aws.amazon.com/fsx/latest/APIReference/API_FileSystem.html) defines `FileSystemTypeVersion` as "The **Lustre version** of the Amazon FSx for Lustre file system, which can be `2.10`, `2.12`, or `2.15`" — it is not a field that carries an ONTAP version.

```
top-level keys      : AdministrativeActions, CreationTime, FileSystemId, FileSystemType,
                      KmsKeyId, Lifecycle, NetworkInterfaceIds, NetworkType,
                      OntapConfiguration, OwnerId, ResourceARN, StorageCapacity,
                      StorageType, SubnetIds, Tags, VpcId
OntapConfiguration  : DeploymentType, DiskIopsConfiguration, Endpoints, HAPairs,
                      PreferredSubnetId, ThroughputCapacity,
                      ThroughputCapacityPerHAPair, WeeklyMaintenanceStartTime
```

Checking the version requires the ONTAP CLI (`cluster image show`) or the ONTAP REST API (`/api/cluster?fields=version`). The management endpoint is reachable only from inside the VPC, so a bastion or EC2 instance in the VPC is needed. It was confirmed to be unreachable from the host used in this session.

This carries an operational implication: if a version-dependent requirement is documented in future, **whether it is satisfied cannot be determined from the AWS API alone**.

---

## 8. Post-Migration Storage Structure and Operational Notes

All [Documented]. Sources: [FSx for ONTAP configuration](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html) and the [AWS Storage Blog](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/).

### 8.1 LUN and volume layout

During migration, **one volume is created per source server**, and each disk is placed as a **separate LUN** within that volume. A server with three disks becomes "one volume + three LUNs".

The ONTAP recommended layout is one volume to one LUN. Under this structure, snapshot policies, tiering policies, and storage efficiency cannot be set per disk. After migration, LUNs can be relocated into dedicated volumes with `lun move start`. That operation is non-disruptive and requires no iSCSI reconfiguration on the host.

### 8.2 Settings that are not carried over

When the source is an existing ONTAP system, access permissions, quotas, snapshot policies, and schedules are **not migrated automatically**. Reconfigure them on the target after migration.

### 8.3 Items to address before Finalize

| Item | Detail |
|---|---|
| Automatic backups | FSx for ONTAP automatic backups are enabled by default. Locked snapshots created by backups can block the FlexClone split. Disable before Finalize, wait for cleanup to complete (up to 24 hours), then re-enable |
| ARP | If ONTAP Autonomous Ransomware Protection is enabled, disable it before migration. It can block deletion of replication volumes. Re-enable after cutover |

### 8.4 Do not touch MGN-managed resources

Do not rename or modify the FSx for ONTAP resources that MGN manages (LUNs, igroups, snapshots). Doing so disrupts the migration and **requires restarting from the beginning**.

---

## 9. Constraints, Risks, and Prerequisites

### 9.1 Irreversible operations

**Finalize is irreversible.** At that stage ATX splits the FlexClone from its parent replication volume, stops replication, and terminates staging resources. Complete connectivity checks and acceptance testing on the cutover instance before running it.

**This was confirmed by measurement** (12.10). Calling `change-server-life-cycle-state` after Finalize is rejected, and the error text directs you to reinstall the replication agent to restart the migration. Replication from scratch is the only way back.

The mechanism that makes it irreversible, and how far back you can go before it, are set out in 9.7.

Before Finalize, rollback is available: if the cutover instance shows a problem, the server can be returned to "Ready for cutover". Replication never stopped, so no re-baselining is required.

Separately, changing the storage type on a server that is already replicating **terminates the current replication and restarts it from the beginning**. Decide the storage type before starting.

### 9.2 Configuration constraints

| Constraint | Detail |
|---|---|
| Boot volume | Always EBS. Booting directly from FSx for ONTAP is not possible |
| Replication method | Agent-based only |
| Mixing within a server | All data volumes of one source server use the same storage type. Mixing EBS and FSx for ONTAP is not allowed |
| Number of file systems | Up to 5 concurrently per account. Split into phases beyond that |
| igroup limits | 256 for Single-AZ, 512 for Multi-AZ. MGN creates one per source server during replication and one per target instance at launch, so size the number of servers per file system at design time |
| Local Zones | Not supported |
| Multi-AZ endpoint | The endpoint IPv4 range must be specified explicitly from RFC 1918 space and **outside the VPC CIDR** (unallocated / floating is not accepted) |

### 9.3 Capacity and throughput prerequisites

| Item | Guidance |
|---|---|
| Storage capacity | Provision **3x** the migration data volume, because replicated data, converted volumes for launch, and original volumes pending deletion coexist. Deletion is a background operation, so capacity is not freed immediately |
| SSD utilization | Keep at or below 80% throughout the migration |
| Throughput | Sum average read and write throughput across all source servers, add 15% headroom, and round up to a supported value. Changes take time to apply, so decide before starting |
| Reduction | On second-generation file systems (Single-AZ 2 / Multi-AZ 2), capacity can be reduced after migration. Throughput can be reduced after migration |

### 9.4 Permission and authentication prerequisites

| Item | Detail |
|---|---|
| MGN initialization | Must be initialized with agent-based replication. **Environments initialized before FSx for ONTAP support require Settings -> Replication template -> Reinitialize Service Permissions** |
| Authentication method | Certificate-based. Required for access to the ONTAP REST API and iSCSI targets. CHAP is not used |
| Private key format | PKCS#8 (`-----BEGIN PRIVATE KEY-----`). Convert PKCS#1 with `openssl pkcs8 -topk8` |
| Secret structure | Key names must be exactly `cert` and `key`. `certificate` / `private_key` are not accepted. Do not include a `username` field |
| Secret tag | `AWSApplicationMigrationServiceManaged` = `True` |
| Certificate issuer | Self-signed is acceptable for testing. AWS Private CA or an internal CA is recommended for production |

### 9.5 Network prerequisites

| Item | Detail |
|---|---|
| Placement | FSx for ONTAP and MGN instances must be in the same account and Region. The VPC may be the same or different provided both are mutually routable. IPv4 is required |
| Ports | iSCSI 3260, ONTAP REST API / management 443, replication from source 1500 |
| Security group design | Create two groups, one for MGN-launched instances and one for FSx for ONTAP, cross-referencing each other. Specifying the MGN group as the source on the FSx inbound rules denies everything other than MGN-launched instances by default |
| MGN service traffic | 443 must be allowed from the CIDRs of both the preferred and standby FSx subnets |
| Outbound reachability | Both the staging subnet and the launch subnet must reach OS package repositories, because MGN installs iSCSI initiator and multipath packages automatically |
| AZ placement | Place target EC2 instances in the same AZ as the file system's preferred file server to limit latency and cross-AZ transfer cost |

### 9.6 Tagging note

MAP 2.0 tags are applied to the FSx for ONTAP **file system** but **not to individual volumes**. This matters if cost allocation is designed around per-volume tagging.

---

### 9.7 The migration lifecycle and how far rollback reaches [Documented]

Source: [Migrate VMware Storage to Amazon FSx for NetApp ONTAP using AWS Transform (AWS Storage Blog)](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)

The official blog describes the migration in five stages. **Why Finalize is irreversible, and why everything before it can be retried indefinitely, both follow from how FlexClone is used.**

| Stage | What happens | State of replication |
|---|---|---|
| 1. Continuous replication | A full initial copy, then only changed data. An interruption resumes from where it stopped rather than starting over | Running. The source is not taken down |
| 2. Non-disruptive, repeatable testing | A **FlexClone** of the replicated volume is created and attached to a test instance over iSCSI (multipath I/O auto-configured). Boot is on EBS | **Continues. The FlexClone is independent, so replication is not interrupted** |
| 3. Cutover | Any previously launched test instance and its dependent resources are deleted first, then a cutover instance is launched from the latest state | Continues |
| 4. Rollback | If a problem appears after cutover, the server returns to "Ready for cutover". **No re-baselining**, repeatable as many times as needed | **Continues. Cutover does not end replication** |
| 5. Finalize | The FlexClone is split from its parent into an independent volume. Staging resources are terminated and the source is marked "Cutover complete" | **Stops. This is the first point at which it stops** |

Three things follow.

**Testing is repeatable because the FlexClone is independent.** A FlexClone is an instant writable copy that shares blocks with the original volume and sits outside the replication stream. Replication therefore keeps running during a test, and a failed test can be fixed and retried. What is tested is the actual target storage, not a simulation.

**The irreversible point is Finalize, not cutover.** The replication stream is independent of test and cutover operations and stops only when Finalize is chosen explicitly. The source therefore remains synchronized as a safety net even after cutover.

**This is also why automatic backups block Finalize.** Locked snapshots created by backups **obstruct the FlexClone split** (8.3). Backups are a file-system setting, so on a shared file system the effect reaches every co-located volume (5.5).

### 9.8 How this differs in character from other methods, and how to treat the published figures [Documented]

**The reach of rollback differs by method.** This is a question of fit against requirements, not of one being better.

| Aspect | Agent-based (ATX / MGN) | SnapMirror-based paths |
|---|---|---|
| Sync before cutover | Continuous replication, maintained during testing | Pre-sync completed, then broken at switchover |
| When it becomes irreversible | Finalize, an explicit action | The break, which conversion depends on. Recoverable by resync, at the cost of a delta transfer |
| Repeating a test | Any number of times, via FlexClone | Requires a resync, since the break is a precondition |
| Where it fits | Minimizing downtime, repeating tests | Reusing already-synced volumes in an existing ONTAP estate and converting quickly |

On **cutover downtime**, the blog states that the window is limited to the time between stopping writes on the source and bringing up the target, and is minutes for most workloads [Documented]. No measurement conditions are given, so it is **usable as a starting point for an estimate but is not a measured value**. It was not measured here either (U3).

**How to treat the published storage-efficiency figures**: the blog states that post-migration data volumes get inline deduplication, compression, and automatic tiering to S3 for 65-80% space savings. The nature of the data, the configuration, and the measurement method are **not stated**. It cannot ground a capacity plan. It becomes a planning number only once measured against your own data. The same applies to the general on-premises figure of 60-80% reduction from thin provisioning, inline deduplication, and compression.

For the same reason, the blog's "Multi-AZ HA with automatic failover and zero RPO" presumes a Multi-AZ deployment. Both file systems in this verification environment are Single-AZ, so that characteristic does not apply here (5.1).

## 10. Coordination with the FSx for ONTAP Adoption Playbook

The sibling repository [FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) contains content that should be updated to reflect this GA.

### 10.1 Existing content requiring update

The section "AWS Transform が FSx for ONTAP をサポート（Public Preview, 2026-06）" in `docs/ja/reference/recent-updates.md` currently assumes Public Preview and recommends waiting for GA before production use. Since GA has shipped, **that statement is stale**. Key points for the update:

| Update point | Detail |
|---|---|
| Status | Public Preview -> GA (2026-08-30) |
| Recommendation wording | Remove "wait for GA" and replace it with the Section 9 constraints (boot fixed to EBS, 5-file-system limit, Finalize irreversible) |
| Scope clarification | Separate "storage target" from "VMware datastore". The latter is on the EVS side and has a different status |
| Sources | Add What's New 2026-09 and ATX Change log 2026-08-30 |

The summary line in the same document, "VMware 移行パスの追加 — AWS Transform と Amazon EVS が FSx for ONTAP をストレージターゲットとしてサポート", also collapses the two paths into one phrasing. ATX provides a storage target and EVS provides a datastore, and their statuses differ (GA versus Public Preview). They need to be written separately.

### 10.2 Existing notes to cross-reference

This GA falls within the scope of the Playbook's `03-migrate` playbook. The strongest relationships are below.

| Playbook note | Relationship to this GA |
|---|---|
| The rollback window closes when clients start writing | In ATX the irreversible point is Finalize. Before that, rollback is available and replication continues, which differs from SnapMirror-based paths |
| Migration method decision tree | Alongside SnapMirror / DataSync / host-side copy, an agent-based plus iSCSI-target option now exists |

### 10.3 Vocabulary mapping

The mapping between the Playbook evidence tiers and this report's tags is given in Section 2. The Playbook evidence policy explicitly states that an external repository's `unverified` maps onto `documented` unchanged, and that the absence of documentation is not a tier. Accordingly, those [Unverified] items here for which no public information exists (the ONTAP version requirement, the EVS GA status) should be carried into the Playbook as body text stating the search date and scope, rather than as a tier.

---

## 11. Unverified Items and Next Actions

### 11.1 Unverified items

| # | Item | Status | Why |
|---|---|---|---|
| U1 | That FSx for ONTAP can be specified as a target | **Resolved** (4.4, 4.5) | Measured via both the API and the console. Screenshots captured |
| U2 | End-to-end migration execution | **Resolved** (section 12) | Completed from test-instance launch through cutover and **Finalize** (12.10), with data integrity matching |
| U3 | Elapsed times | **Resolved** (12.1, 12.9) | Initial full sync 226s. With the correct sequence, the MGN job took 649s and 817s elapsed from T0 to boot confirmation. A single measurement; other configurations not measured |
| U4 | Real behaviour of LUN / volume conversion | **Resolved** (12.3, 12.4, 12.9) | One parent volume plus a LUN per disk, the FlexClone, two igroups, and two multipath devices all measured. Timestamps map the SNAPSHOT phase to a volume Snapshot and the LAUNCH phase to FlexClone creation |
| U5 | Real behaviour of post-migration optimization via `lun move start` | Unverified | U2 is resolved, but `lun move` after migration was not run here. Straight after migration every LUN of one server sits in a single volume (12.3), so this is needed when recovery granularity has to be separated |
| U6 | Minimum ONTAP version requirement | Unverified | No statement found in public documentation (searched 2026-09-04) |
| U7 | GA status of EVS + FSx for ONTAP | Unverified | No GA announcement found (searched 2026-09-04) |
| U8 | Correspondence between `SETUP_FSX_PROXY` and automatic PrivateLink establishment | **Resolved** (12.2) | Creation of an NLB and a VPC endpoint service measured, with `mgn.amazonaws.com` as the allowed principal |
| U9 | Root cause of the `initialize-service` (CLI) failure | **Resolved** | Not a defect. The API path expects 8 IAM roles to be created first and they were not. CloudTrail in us-east-1 records the `AddRoleToInstanceProfile` `NoSuchEntityException` (5.4) |
| U10 | Whether MGN initialization succeeds from the console | **Resolved** (5.4) | Succeeded. 9 roles created, including the 2 FSx-specific ones |
| U11 | Actual SSD usage on the candidate file system | **Resolved** (5.6) | Aggregate 861.8 GiB, 50.0 GiB used, 5.8% utilization |
| U12 | Completing the template save (committing the FSx for ONTAP configuration) | **Resolved** (4.6) | Certificate authentication verified with a negative control, and the save confirmed by API read-back |
| U13 | Official documentation of the additional-security-group requirement | Unverified | Seen only in the console validation message and on-screen help. No corresponding statement found in the MGN User Guide procedure text (searched 2026-09-04) |
| U14 | Whether the certificate and login can be scoped to an SVM | **Untested (future work)** | The created SVM has its own management LIF so it might work, but the official procedure specifies the admin vserver, and departing from it makes failures hard to triage. Cluster scope is now confirmed working, so there is a baseline to compare against |
| U15 | ONTAP version requirement for running replication | **Resolved** (section 12) | Replication and test launch both succeeded on 9.18.1P3D1. No version-related problem arose |
| U16 | Real behaviour of Finalize (the FlexClone split) | **Resolved** (12.10) | Run with approval. Split starts about 3 minutes in and finishes in under 60s (7.93 GiB); staging is deleted about 13 minutes in. **Non-disruptive**, with data matching. No job record is created |
| U18 | Cutover downtime with the correct sequence (application only stopped) | **Resolved** (12.9) | Run with the OS and agent left up; SNAPSHOT succeeded in 44s. MGN job 649s, 817s from T0 to boot confirmation |
| U19 | Extent of delta lost when `SNAPSHOT_FAIL` occurs | Unverified | No delta existed here (zero lag, no writes), so the impact could not be observed |
| U22 | Official documentation that re-onboarding discards launch-template customizations | Unverified | Measured: the replacement template was created with MGN defaults (12.9). No statement found in public documentation (searched 2026-09-04) |
| U20 | Whether cutover succeeds after correcting the disk assignment | **Resolved** (12.9) | Re-onboarding produced a consistent assignment, and both boot and data integrity succeeded, confirming the 12.8 diagnosis |
| U21 | How to make MGN re-evaluate a stale disk assignment | **Resolved** (2026-09-09) | `update-replication-configuration` cannot repair it (three contradictory errors; `isBootDisk` is read-only). **The documented route is rerunning the installer**: [step 6 of the agent installation](https://docs.aws.amazon.com/mgn/latest/ug/linux-agent.html) names it as the way to restore a replicated-disk list that no longer matches the machine. Deleting the source server is not needed; the delete-and-re-onboard used here was the heaviest option available. Whether `stagingDiskType` is re-derived as well is not settled by that text and is unverified |
| U17 | Billing impact of the NLB | Not calculated (**persistence now known**) | The NLB persists **beyond Finalize, not just for the duration of replication** (12.10), and requires manual teardown. No statement was found in public documentation and the cost was not estimated |
| U23 | Official documentation that Finalize leaves the NLB and VPC endpoint service | Unverified | Measured: not deleted through T0 + 36 min (12.10). The EBS volumes are deleted after about 33 minutes. No statement found in public documentation (searched 2026-09-04) |

### 11.2 Candidate next actions

**The end-to-end path is complete through Finalize (U2, U16, U18, U20).** What remains unverified falls into three groups.

| Group | Items | How to proceed |
|---|---|---|
| Can be verified further on this environment | U5 (post-migration optimization via `lun move start`), U14 (SVM-scoped certificate) | Both are testable here. For U14, the working cluster-scope setup provides a baseline for comparison |
| Waiting on public documentation | U6 (minimum ONTAP version), U7 (EVS GA), U13 (the additional-security-group requirement), U22 (template recreation on re-onboarding), U23 (resources left by Finalize) | Wait for updates or ask AWS / NetApp. Treat as [Unverified] until reflected in public docs |
| Needs a different environment | U19 (extent of delta lost on `SNAPSHOT_FAIL`), U17 (NLB cost) | U19 needs a source with continuous writes; U17 needs billing data |

**Teardown is required after migration completes.** Finalize does not finish the cleanup (12.10). **The teardown was carried out here, and its dependencies and timings are recorded in Section 13.** Three things warrant attention during teardown.

- The NLB and the VPC endpoint service are not removed by Finalize and must be deleted manually (13.1)
- A cluster-scope client-ca certificate cannot be deleted with `fsxadmin` (13.3)
- The target instance's root EBS volume remains even after the instance is terminated (13.4)

One point bears repeating about running this on a shared file system: **disabling automatic backups applies to the entire file system**, so a production-equivalent verification should use a dedicated file system (5.3). ARP can be controlled per volume or SVM, so a dedicated SVM isolates it (5.5).

---

## 12. End-to-end execution results [Measured / 2026-09-04]

A source server was prepared (Amazon Linux 2023, 8 GiB boot plus two 4 GiB data disks) and taken from agent installation through test-instance launch, cutover, a data-integrity check, and **Finalize**. Because Finalize is irreversible, it was run only after approval (9.1).

Two failures occurred along the way. As a reading order: 12.1-12.6 is the working path, 12.7 and 12.8 are the failures and their diagnosis, 12.9 is the success after correction, and 12.10 is Finalize. **If you only need the outcome, read 12.9 and 12.10.**

### 12.1 Elapsed times

| Interval | Measured |
|---|---|
| Initial full sync (16 GiB across 3 disks) | **226 seconds** |
| Agent installation complete to `READY_FOR_TEST` | About 20 minutes, including the `CREATING_SNAPSHOT` wait |
| Test launch: SNAPSHOT | 43 seconds |
| Test launch: CONVERSION | About 4 minutes 30 seconds |
| Until iSCSI sessions established after launch | Several minutes; the count is 0 immediately after launch |

The last row invites a wrong call. **Seeing zero sessions right after launch completes is not evidence of failure.**

### 12.2 What SETUP_FSX_PROXY actually is

Section 4.3 established the step's existence from the API model and inferred it corresponded to the blog's "automatically establishes a PrivateLink connection". That is now measured. The step **creates the following inside the customer's VPC**.

| Resource | Detail |
|---|---|
| Internal Network Load Balancer | `MgnFSxProxy<file-system-id>NLB` |
| Target group | `MgnFSxProxy<file-system-id>TG`, TCP/443, target type `ip`, targeting the **FSx management endpoint IP**, health `healthy` |
| VPC endpoint service | Fronting that NLB, with `AcceptanceRequired: true` |
| Connection acceptance | `mgn.amazonaws.com` (Service) is registered as an allowed principal, and an endpoint owned by an AWS-side account becomes `available` automatically |

The MGN service therefore reaches the ONTAP REST API (443) over PrivateLink, through an NLB in the customer's VPC. The design avoids exposing the management endpoint externally.

**Cost implication**: an **NLB runs in the customer's account for the duration of replication**, incurring NLB hourly and LCU charges. No statement of this was found in the AWS documentation or blog consulted (searched 2026-09-04). It belongs in a migration cost estimate.

### 12.3 Measured storage layout

| Item | Measured |
|---|---|
| Parent volume | `replication_<source-server-id>_<timestamp>`, 10.00 GiB (against 8 GiB of LUNs) |
| Clone volume | `target_<source-server-id>_<timestamp>`, `is_flexclone: true`. **Created at LAUNCH_START** |
| LUN names | Preserve the source device path, URL-encoded (`{2f}dev{2f}nvme1n1` = `/dev/nvme1n1`) |
| igroups | Two: `replication-<id>` (the replication server's IQN) and `target-<id>` (the target's IQN) |
| LUN maps | Assigned at LUN IDs 0 and 1 within each igroup |
| Volume settings | `guarantee: none` (thin), `snapshot_policy: none`, efficiency `compression=inline` / `dedupe=both` / `compaction=inline` enabled by default, `tiering: snapshot_only` (min_cooling_days 2) |

The 8 GiB boot disk did not appear on FSx. It existed as an **EBS gp3 staging volume** attached to the replication server, confirming "boot on EBS, data on FSx" at the storage layer.

### 12.4 How it presents in the guest, and data integrity

Measured on the test instance.

| Item | Measured |
|---|---|
| Boot | `nvme0n1` 8 GiB, mounted at `/` (EBS) |
| Data | 4 paths (`sda` through `sdd`) resolving to **2 multipath devices**, `NETAPP,LUN C-Mode`, hwhandler `alua` |
| iSCSI sessions | 2, one to each FSx iSCSI endpoint |
| Multipath priority | prio 50 `active`, prio 10 `enabled` (ALUA optimized and non-optimized) |
| Data integrity | **All four sha256 values match the source** (64 MiB of random data plus a marker file, on each of two disks) |

**The data disks were not mounted automatically.** The device path changes from `/dev/nvme1n1` on the source to `/dev/mapper/<WWID>` on the target, so an `/etc/fstab` written against device names will fail to mount. **Entries must use UUID or LABEL.** This verification mounted by label to complete the integrity check.

### 12.5 Failures encountered, and their causes

No statement covering any of these was found in the public documentation.

| # | Symptom | Error shown | Actual cause and fix |
|---|---|---|---|
| 1 | Agent installation failed | "Are kernel linux headers installed correctly?" | **The kernel headers were present.** The real cause was `No space left on device`. On AL2023 `/tmp` is a tmpfs sized from RAM (955 MiB on a t3.small), and the kernel-module build exhausted it. Resolved by pointing `TMPDIR` at a disk-backed path |
| 2 | Test launch failed | `VPCIdNotSpecified: No default VPC for this user` | MGN's default launch template carries `NetworkInterfaces` without a subnet and falls back to the default VPC, which fails in an account that has none. Resolved by creating a template version with explicit `SubnetId` and `Groups`. **The failure was non-destructive: replication stayed `CONTINUOUS` / `READY_FOR_TEST`** |
| 3 | Target absent from SSM | `ConnectionLost` | The launch template carries no IAM instance profile. Resolved by attaching one. Because the source had been launched without a key pair, there was no SSH fallback, which narrowed the diagnostic options |

The lesson from item 1 generalizes. **An installer's hint is not necessarily the cause.** Read the error code (`NO_SPACE_LEFT_ON_DEVICE` here) rather than the tail of the log.

Separately, the **"Volume integrity validation" post-launch action from Step 7 of the official procedure was not enabled**. It automatically verifies iSCSI connectivity and multipath mounting, which would have replaced the manual checks in 12.4. It should have been enabled before launch.

### 12.6 Not done, and what remains unverified

| Item | Status |
|---|---|
| Finalize | **Run** (12.10), with approval |
| Cutover | **Run** (12.7, 12.9), with data integrity matching |
| Measured cutover downtime | **Re-measured in 12.9**: 649s of MGN work, 817s from T0 to boot confirmed. The 12.7 value includes procedural error and cannot stand as a product characteristic |
| Post-migration optimization via `lun move start` | Not done (U5 stands) |
| Real behaviour of rollback (revert) | Not done. **No longer possible now that Finalize has run** (rejection confirmed in 12.10) |
| Console screenshots for this section | Not captured; API-level evidence only |

### 12.7 Measured cutover, and the failure the job status concealed

After the test launch, the lifecycle was moved to `READY_FOR_CUTOVER` and cutover was run. **Finalize was not run.**

The lifecycle transition needs its own API. Calling `start-cutover` while in `TESTING` returns `ConflictException` (wrong lifecycle state). Use `change-server-life-cycle-state` with `READY_FOR_CUTOVER`.

#### Job phase breakdown

| Time (UTC) | Delta | Event |
|---|---|---|
| 09:13:45 | — | JOB_START |
| 09:13:46 | +0s | CLEANUP_START (**deletion of the preceding test instance**) |
| 09:14:21 | +35s | CLEANUP_END |
| 09:14:21 | +0s | SNAPSHOT_START |
| 09:19:22 | **+300s** | **SNAPSHOT_FAIL** |
| 09:19:23 | +0s | **USING_PREVIOUS_SNAPSHOT** |
| 09:22:46 | +202s | CONVERSION_END |
| 09:28:20 | +333s | LAUNCH_END |

CLEANUP running first matches the blog's statement that each new cutover first deletes any previously launched test instance and its dependent resources.

#### Job success concealed a failure

**The job returned `COMPLETED` / `LAUNCHED`, but the final snapshot had failed.** It timed out after 300 seconds and fell back to the preceding snapshot via `USING_PREVIOUS_SNAPSHOT`. Watching only the job status would miss this.

The cause was an error in this verification's procedure. To measure downtime, the **source OS was stopped**, which also stopped the replication agent. MGN needs agent coordination to take a crash-consistent snapshot, so it could not reach the agent and timed out.

**The correct sequence is to stop the application (the writes) while leaving the OS and agent running.** The documentation's phrase "between stopping writes on the source and bringing up the target" does not mean stopping the OS.

Data still matched here, because lag was zero before cutover and no writes occurred after the marker was written. But **doing the same thing in a live environment with ongoing writes would lose the delta covered by the fallback**. The job status does not surface that risk.

**Lesson**: after a cutover, always read `describe-job-log-items` and look for `SNAPSHOT_FAIL` and `USING_PREVIOUS_SNAPSHOT`. A `COMPLETED` job is not evidence that a final sync succeeded.

#### Breakdown of the outage window

| Interval | Measured | Nature |
|---|---|---|
| T0, writes stopped (OS shutdown initiated) | 09:12:07 | — |
| Source fully stopped | 09:12:54 (47s) | Caused by this verification's procedure |
| Until `start-cutover` was issued | 09:13:45 (+51s) | **Procedural error here** (lifecycle transition not done in advance) |
| MGN job | 875s | Of which 300s was the failed snapshot wait |
| Until SSM was reachable | +141s | **Because the launch template carries no IAM profile** (12.5, item 3) |
| T1, data verified | 09:31:29 | — |
| **Total** | **19 minutes 22 seconds** | — |

**This 19m22s must not be quoted as the product's cutover downtime.** Roughly 8 minutes of it stems from procedural mistakes and configuration gaps specific to this run: the missed lifecycle transition, the failed snapshot, and the absent IAM profile. MGN's actual work was CLEANUP 35s + CONVERSION 202s + LAUNCH 333s = **about 9 minutes 30 seconds**.

Run in the correct order, a workload of this size (16 GiB across 3 disks) would plausibly land near 10 minutes, but **that was not measured here**. The blog's "minutes for most workloads" is not contradicted in order of magnitude, but cannot be said to be confirmed.

#### State after cutover

| Item | Value |
|---|---|
| Lifecycle | `CUTTING_OVER`, not `CUTOVER`, because Finalize was not run |
| Replication | `STALLED`, since the source OS was stopped and the agent is absent |
| Data integrity | **All six sha256 values match**, including the marker written immediately before cutover |
| Guest side | 2 iSCSI sessions, 2 multipath devices, identical to the test launch |
| Rollback | **Still available.** Finalize has not run, so `revert` returns the server to `READY_FOR_CUTOVER` |

### 12.8 Root cause of the unbootable target: device re-enumeration and a stale disk assignment

The correctly-sequenced cutover was run twice, and **both produced an unbootable instance**. Triage identified the cause as a stale MGN disk assignment resulting from device-name instability.

#### Symptom

The target instance enters a UEFI shell reboot loop.

```text
No boot device
Dropping to the EFI Shell.
The system will reboot in 60 seconds.
```

The UEFI mapping table shows one boot NVMe device (data disks are attached over iSCSI and are not visible to UEFI, which is expected). **The disk is present but holds nothing bootable.**

#### Triage

The unbootable instance's boot EBS volume was detached and attached to the running source for inspection.

| Check | Result |
|---|---|
| Partition table | **None** (the full 8 GiB reported as free) |
| Filesystem | XFS written **directly to the raw device** |
| Label | `data_nvme1n1`, a **data disk's label** |
| XFS size | agcount 8 x agsize 131072 blks x 4096 = **4 GiB** (a 4 GiB filesystem on an 8 GiB volume) |
| EFI System Partition | **None** |

The 8 GiB EBS volume provisioned for the boot disk therefore contained **the contents of a 4 GiB data disk**.

#### Cause

MGN's recorded disk assignment had diverged from the source's actual layout.

| MGN's assignment | What that device actually is now | Correct assignment |
|---|---|---|
| `/dev/nvme0n1` → `AUTO` (EBS, boot) | 4 GiB **data** disk | FSX_ONTAP |
| `/dev/nvme1n1` → `FSX_ONTAP` | **8 GiB boot disk** (`/` is `/dev/nvme1n1p1`) | AUTO (EBS) |
| `/dev/nvme2n1` → `FSX_ONTAP` | 4 GiB data disk | Correct |

**The assignment is inverted.** As a mirror-image confirmation, the FSx LUN sizes had changed.

| LUN | First run (successful) | Now |
|---|---|---|
| `/dev/nvme1n1` | 4.00 GiB | **8.00 GiB** |
| `/dev/nvme2n1` | 4.00 GiB | 4.00 GiB |

The presence of an 8 GiB LUN means **the boot disk is being replicated to FSx**.

The causal chain is:

1. The **source instance was stopped and restarted** to measure downtime (the procedural error in 12.7)
2. The restart caused **NVMe device names to be re-enumerated**. The boot disk moved from `/dev/nvme0n1` to `/dev/nvme1n1`
3. MGN's staging-type assignment in `replicatedDisks` **is keyed on device name and was not re-evaluated** after the names shifted
4. As a result the boot disk replicated to an FSx LUN, and a data disk replicated to the EBS boot volume
5. The target had nothing bootable and dropped to the UEFI shell
6. **MGN still reported the job as `COMPLETED` / `LAUNCHED`**

The test launch and the first cutover succeeded because they ran **before the source was stopped**, while the assignment was still correct.

#### The generalizable implication

This is not an artifact of this verification; it is **a hazard that can occur in production**.

| Aspect | Detail |
|---|---|
| Trigger | The source reboots after agent installation and device enumeration order changes. NVMe enumeration order is not guaranteed |
| Effect | Boot and data storage assignments invert, producing an unbootable target |
| Difficulty of detection | The MGN job reports success. No log event comparable to `SNAPSHOT_FAIL` is emitted |
| Data loss | None here: the source is untouched and replication continues. But **finalizing without noticing the migration failed would remove the recovery path** |

**Mitigations**:

- Before cutover, read `replicatedDisks` from `get-replication-configuration` and verify by size that the device corresponding to the boot disk is assigned `AUTO` (EBS)
- Cross-check the sizes in `sourceProperties.disks` from `describe-source-servers` against `lsblk` on the machine
- Do not reboot the source after agent installation. If a reboot is unavoidable, re-verify the assignment
- Enable the **Volume integrity validation post-launch action** from Step 7 of the official procedure. It automates post-launch checking and would have caught this early

The assignment was corrected and the cutover re-run in 12.9, which confirmed this diagnosis.

### 12.9 Successful cutover after correcting the assignment [Measured / 2026-09-04]

The inverted assignment from 12.8 was corrected and the cutover re-run in the correct sequence. **Both boot and data integrity succeeded.** This confirms the 12.8 diagnosis.

#### Choosing the remediation

`update-replication-configuration` could not repair it. Attempting to change the staging type in `replicatedDisks` returns **three mutually contradictory errors**.

| Attempt | Error returned |
|---|---|
| `FSX_ONTAP` on the data disks only | `FSX_ONTAP requires FSX_ONTAP staging disk type for all volumes` |
| `FSX_ONTAP` on all disks | `InternalServerException` |
| An EBS equivalent on the boot disk | `EBS cannot use FSX_ONTAP staging disk type` |

`isBootDisk` is not accepted as an input field (read-only). **No API route to correct the assignment was found**, so the source server was deleted, the agent reinstalled, and the server re-onboarded.

After re-onboarding the assignment matched the actual layout.

| Device | Size | `isBootDisk` | `stagingDiskType` |
|---|---|---|---|
| Boot | 8 GiB | `true` | `AUTO` (EBS) |
| Data 1 | 4 GiB | `false` | `FSX_ONTAP` |
| Data 2 | 4 GiB | `false` | `FSX_ONTAP` |

#### Side effect of re-onboarding: the launch template is recreated

**Re-onboarding created a new launch template, losing both the subnet specification added in 12.5 #2 and the IAM profile handling from #3.** Deleting a source server detaches its launch template, and the replacement is created with MGN defaults, so `VPCIdNotSpecified` recurs in an account with no default VPC.

**Re-onboarding is not just reinstalling the agent.** Launch-setting customizations have to be redone each time.

#### Pre-cutover cross-check (a step added here)

To prevent a recurrence of 12.8, the following was cross-checked before issuing the cutover. This step is not part of the official procedure, but **it is worth adding**.

1. From `get-replication-configuration` `replicatedDisks`: which device has `isBootDisk: true`, and its `stagingDiskType`
2. From `describe-source-servers` `sourceProperties.disks`: the size of that same device name
3. `lsblk` output on the source machine

Issue the cutover only after confirming the boot device is 8 GiB and its `stagingDiskType` is not `FSX_ONTAP`.

#### Job phase breakdown

T0 (`start-cutover` issued) = 12:04:57 UTC. The **source OS and agent were left running**, with no application writes in flight.

| Time (UTC) | Elapsed from T0 | Event |
|---|---|---|
| 12:04:59 | +2s | JOB_START |
| 12:05:00 | +3s | SNAPSHOT_START |
| 12:05:44 | +47s | SNAPSHOT_END (**succeeded in 44s**) |
| 12:05:45 | +48s | CONVERSION_START |
| 12:10:09 | +312s | CONVERSION_END (264s) |
| 12:10:10 | +313s | LAUNCH_START |
| 12:15:47 | +650s | LAUNCH_END (337s) |
| 12:15:48 | +651s | JOB_END |

**No `SNAPSHOT_FAIL` and no `USING_PREVIOUS_SNAPSHOT`.** The phase that timed out after 300s in 12.7 completed normally in 44s. The only difference was not stopping the source OS, which corroborates the 12.7 diagnosis (the agent was absent).

**There is no CLEANUP phase.** 12.7 spent 35s deleting the preceding test instance; here the source server had been deleted and re-onboarded, so there was nothing to delete.

#### From T0 to verification complete

| Interval | Measured | Nature |
|---|---|---|
| MGN job (JOB_START → JOB_END) | **649s** | Product work |
| LAUNCH_END → instance status `ok`/`ok` | 167s | Waiting for the OS to boot |
| T0 → boot confirmed | **817s (13m37s)** | — |
| T0 → data integrity confirmed | about 15 min | Includes manual mounting and sha256 |

Of the difference from 12.7's 19m22s, 300s was the failed snapshot and 51s the missed lifecycle transition. **At this scale (16 GiB across 3 disks), MGN's actual work was about 11 minutes.** This is a single measurement; behaviour at other disk counts, sizes, or regions was not measured.

#### Boot succeeded

| Check | Result |
|---|---|
| Instance status | `ok` / `ok` (the unbootable instance in 12.8 never reached this) |
| Root device | `/dev/sda1` → `nvme0n1` in the guest, 8 GiB gp3 EBS |
| Partitions | `nvme0n1p1` (XFS, `/`), `p127` (BIOS Boot), `p128` (vfat, `/boot/efi`) |
| Console output anomalies | `No boot device` / `EFI Shell` / `Boot Failed`: **0 occurrences** |
| SSM | `Online` about 3 minutes after LAUNCH_END |

The EFI system partition and the partition table, both missing in 12.8, were present.

#### Data integrity

sha256 values recorded on the source beforehand were compared against values recomputed on the target.

| File | Written | Match |
|---|---|---|
| `payload.bin` (64 MiB) | Before the initial full sync | Matched on both disks |
| `marker.txt` | Before the initial full sync | Matched on both disks |
| `cutover.txt` | Just before the first cutover | Matched on both disks |
| `delta.bin` (32 MiB) / `delta.txt` | For delta-sync verification | Matched on both disks |
| `retry.bin` (16 MiB) / `retry.txt` | Before the re-run cutover | Matched on both disks |

**All 14 files, and all 8 pre-recorded hashes, matched.**

The guest-side presentation is the same as 12.4: 2 iSCSI sessions, 2 multipath devices, `NETAPP,LUN C-Mode`, hwhandler `alua`, prio 50 `active` and prio 10 `enabled`. The XFS labels (`data_nvme1n1` / `data_nvme2n1`) were preserved from the source.

`iscsid` and `multipathd` are `enabled` (start at boot). However **no `/etc/fstab` entries were created for the data volumes**. Configuring persistent mounts remains post-migration work.

#### Launch via FlexClone: what the SNAPSHOT and LAUNCH phases actually are

Cross-checking the ONTAP side established which ONTAP operation each MGN phase name corresponds to.

| MGN phase | Corresponding ONTAP operation | Measured |
|---|---|---|
| SNAPSHOT | A **volume Snapshot** of the staging FlexVol | Created at 12:05:05 UTC, inside the SNAPSHOT_START–END window |
| LAUNCH | A **FlexClone** from that Snapshot | Target FlexVol creation time 12:10:41 UTC |

The target volume has `is_flexclone: true`, with `parent_volume` set to the staging volume and `parent_snapshot` to the Snapshot above. The staging volume shows `has_flexclone: true`.

| Item | Measured |
|---|---|
| `split_estimate` | 8,517,623,808 bytes (about 7.93 GiB) |
| `split_initiated` | `false` (no split running at launch) |
| `inherited_savings` | 2,326,528 bytes |

**There are two implications.**

First, **the SNAPSHOT phase is a metadata operation rather than a copy**, taking 44s for 8 GiB of data. Unlike an EBS-snapshot path, its growth with data volume can be expected to be gentle. But **this verification is a single data point** and the growth curve was not measured.

Second, **the target volume depends on a Snapshot inside the staging volume**. Physical consumption right after launch is only the delta; the `space.used` on both volumes (about 7.9 GiB each) is a logical figure. Because of this dependency, **for Finalize to delete the staging volume it must either split the FlexClone or control the deletion order**. A split entails about 7.93 GiB of writes. **This projection matched the measurement in 12.10** (U16 resolved).

#### ONTAP-side resource naming (measured)

| Object | Naming |
|---|---|
| Staging FlexVol | `replication_<source server ID with underscores>_<YYYYMMDD>_<HHMMSS>_<microseconds>` |
| Target FlexVol | `target_<source server ID with underscores>_<YYYYMMDD>_<HHMMSS>` |
| LUN | `/vol/<FlexVol name>/{2f}dev{2f}<device name>` (`/` preserved as `{2f}`) |
| igroup (replication side) | `replication-<source server ID>`. The initiator IQN embeds the **replication server's EC2 instance ID** |
| igroup (target side) | `target-<source server ID>`. The initiator IQN derives from the source server ID and does not depend on an instance ID |
| iSCSI target | One per SVM. FSx places one iSCSI LIF on each node of the HA pair (2 total) |

The FlexVol was created at 10 GiB for 8 GiB of LUNs, with `guarantee: none` (thin), `snapshot_policy: none`, `efficiency.compression: inline`, and `security_style: unix`. LUN `os_type` is `linux`, and `space.used` is 4,247,678,976 of 4 GiB (98.9%).

The aggregate showed 70.5 GiB used of 861.8 GiB (8.2%). The increase from the 5.6 measurement (50.0 GiB) **cannot be attributed to this verification alone, because the file system is shared.**

Physical consumption of a FlexClone differs sharply from the logical figure. Measured immediately before Finalize:

| Volume | Logical (`space.used`) | Physical (`space.physical_used`) |
|---|---|---|
| Staging (parent) | 8,533,684,224 (7.95 GiB) | 8,628,998,144 (8.03 GiB) |
| Target (FlexClone) | 8,496,549,888 (7.91 GiB) | **37,236,736 (35.5 MiB)** |

**The clone consumes 35.5 MiB of physical space against 7.91 GiB logical.** Capacity planning has to read the physical figure, not the logical one. Finalize inverts this relationship (12.10).

### 12.10 Real behaviour of Finalize [Measured / 2026-09-04]

**Finalize was run with approval.** This resolves U16 and confirms the statement in 9.1 by measurement.

#### State transition on the call

| Item | Change |
|---|---|
| Lifecycle | `CUTTING_OVER` → **`CUTOVER`** (already done by the time the API responds) |
| Data replication | `CONTINUOUS` → **`DISCONNECTED`** (simultaneously) |
| Job record | **None created** |

**Finalize creates no corresponding job.** Unlike cutover or test launch it does not appear in `describe-jobs`, and its phases cannot be followed with `describe-job-log-items`. The subsequent cleanup runs asynchronously, so **the only way to judge progress is to poll resource state directly**.

#### Cleanup timeline

T0 = 12:36:23 UTC (`finalize-cutover` issued), polled at 30-second intervals.

| Elapsed from T0 | Observed change |
|---|---|
| Immediate | Lifecycle `CUTOVER`, replication `DISCONNECTED` |
| about 3 min | **FlexClone split starts** (`split_initiated: true`). Target physical consumption climbing, 35.5 MiB → 3.94 GiB |
| about 4 min | **Split complete** (`is_flexclone: false`). Physical consumption 8.57 GiB |
| about 13 min | Staging FlexVol **deleted**, replication server EC2 **terminated**, staging EBS moved to `available` |
| about 23 min | One EBS volume **deleted** |
| about 33 min | The remaining two EBS volumes **deleted**. Cleanup complete |

The split itself completed between two 30-second samples, so it took **under 60 seconds for 7.93 GiB**. Between split completion and staging-volume deletion, however, there is **a gap of about 9 minutes**.

**Cleanup proceeds in stages over about 33 minutes.** The EBS volumes moved to `available` first and were then deleted at roughly 10-minute intervals (confirmed from CloudTrail `DeleteVolume` events).

> **A note on the observation window**: the first pass observed only 16 minutes from T0 and recorded the three volumes still in `available` as "Finalize does not delete the EBS volumes". **That was wrong.** A recheck at 33 minutes found all of them deleted, and CloudTrail supplied the deletion times for the correction. **Any claim that an asynchronous cleanup leaves something behind has to state the length of the observation window.**

#### Capacity implication: Finalize demands a temporary full copy

The physical relationship inverts across Finalize.

| Point in time | Staging (physical) | Target (physical) | Total |
|---|---|---|---|
| Before Finalize | 8.03 GiB | 35.5 MiB | about 8.06 GiB |
| Just after the split | 8.03 GiB | 8.57 GiB | **about 16.6 GiB** |
| After staging deletion | — | 8.57 GiB | 8.57 GiB |

**Additional physical capacity equal to one copy of the migrated data is required, and here it was held for about 9 minutes.** Running Finalize when aggregate free space is below the migrated data size puts the split under capacity pressure. **Finalize is not a tidy-up step; it is the point of peak capacity.**

The target volume autogrew from 10.00 GiB to 10.19 GiB during the split. Afterwards it holds 0 snapshots and has no remaining dependency on its former parent.

#### Data availability during the split

The target instance kept running throughout the split. Rechecked afterwards:

| Check | Result |
|---|---|
| Mounts | Both retained (not unmounted) |
| sha256 (4 files recomputed) | **All matched** |
| iSCSI sessions | 2 (unchanged) |
| Multipath devices | 2 (unchanged) |
| `dmesg` I/O errors / path down / SCSI aborts | **0** |

**The split completed without disruption.** In terms of business impact, Finalize is a capacity risk rather than an availability risk (observed at this verification's scale and load).

#### Confirming irreversibility

Attempting to move back to `READY_FOR_CUTOVER` with `change-server-life-cycle-state` after Finalize was rejected.

```text
ConflictException: Cannot ChangeServerLifeCycleState for a CUTOVER server.
If you need to restart the migration, reinstall the Replication Agent.
```

**Replication from scratch is the only way back.** As the message indicates, restarting means reinstalling the agent and rebuilding from the initial sync.

#### What Finalize does not clean up

Resources remain after Finalize, and **they keep billing**.

| Left behind | State | Note |
|---|---|---|
| Internal NLB (`MgnFSxProxy<file system ID>NLB`) | `active` | Created in 12.2. **Observed through T0 + 36 min without deletion** |
| VPC endpoint service | `Available` | Same |
| igroup `replication-<source server ID>` | Remains with 0 LUN maps | ONTAP-side residue |
| Target FlexVol, its two LUNs, and igroup `target-<ID>` | In service | The migration target itself. **Keeping it is correct**; removal belongs after the migration is judged complete |

**The EBS volumes do get deleted (after about 33 minutes). The NLB and the VPC endpoint service do not.** The FSx proxy MGN created keeps billing after the migration completes, so **manual teardown is required**. No statement about this residue was found in public documentation (searched 2026-09-04).

The leftover igroup has no functional effect, but it is confusing if the same SVM is reused.

## 13. Teardown procedure and measurements [Measured / 2026-09-04]

The verification environment was torn down. **The shared file system itself (still `AVAILABLE`) and the four SVMs belonging to other workstreams were left untouched**, verified by cross-checking after the deletions.

Dependencies and measured timings are recorded here so that anyone repeating this verification does not get stuck on teardown.

### 13.1 Deletion order and measured times

| # | Target | Method | Measured |
|---|---|---|---|
| 1 | Target EC2, source EC2 | `terminate-instances` | Both `terminated` in 32s |
| 2 | MGN source server | `delete-source-server` | Immediate. **Deletable straight from `CUTOVER`; archiving is not required** |
| 3 | VPC endpoint connection | `reject-vpc-endpoint-connections` | Immediate |
| 4 | VPC endpoint service | `delete-vpc-endpoint-service-configurations` | Immediate |
| 5 | NLB, target group | `elbv2 delete-load-balancer` / `delete-target-group` | Immediate. The listener goes with the NLB |
| 6 | Target FlexVol | **FSx API** `fsx delete-volume` | **70s**. The two LUNs inside were deleted with it |
| 7 | SVM | **FSx API** `fsx delete-storage-virtual-machine` | **100s**. The igroup and the root volume were deleted with it |
| 8 | ONTAP `security login` | REST `DELETE /api/security/accounts/{owner-uuid}/{name}` | Immediate |
| 9 | ONTAP client-ca certificate | — | **Could not be deleted** (13.3) |
| 10 | Replication template | Reset `storageType` to `EBS` | Immediate |
| 11 | Launch template, secret, security groups, IAM role / profile | Respective APIs | Immediate, except the secret's 7-day recovery window |
| 12 | Target's root EBS volume | `delete-volume` | Immediate (13.4) |

### 13.2 Dependencies that needed no manual work

The teardown plan assumed "unmap LUNs → delete LUNs → delete FlexVol", but **the FSx API `delete-volume` deleted the FlexVol with its LUNs still mapped**. Likewise `delete-storage-virtual-machine` deleted the igroup and the root volume along with the SVM.

**For objects the FSx management plane recognizes, deleting from the FSx API side takes fewer steps.** That holds even for volumes MGN created directly over the ONTAP REST API, as long as they appear in `fsx describe-volumes`.

The igroup has no FSx API equivalent, though, so it must be deleted individually over ONTAP REST if the SVM is being kept.

### 13.3 A certificate `fsxadmin` cannot delete

The `security login` could be deleted, but **deleting the client-ca certificate was refused with `fsxadmin` privileges**.

| Route attempted | Result |
|---|---|
| REST `DELETE /api/security/certificates/{uuid}` | **403** `not authorized for that command` (code 6) |
| private CLI passthrough `DELETE /api/private/cli/security/certificate?...` | **403** identical |

The `security login` deletion has its own gotcha: adding `?application=http` returns **400** `Unexpected argument "application"`. The correct call is `DELETE /api/security/accounts/{owner-uuid}/{name}` with no query parameter.

**Access is definitively revoked.** After deleting the login, a negative control was run using the saved client certificate against the ONTAP REST API, confirming it is **rejected with 403** (it returned 200 before deletion). Even with the certificate still installed, authentication fails without the matching `security login`.

| State | Authentication with the client certificate |
|---|---|
| Certificate plus `security login` | 200 |
| Certificate only (login deleted) | **403** |

The remaining certificate is an inert artifact. The four pre-existing certificates (two FSx CAs, one ONTAP self-signed, one SVM-scoped) were confirmed still present afterwards, so **these operations did not affect any other certificate**.

**Implication**: when installing a cluster-scope certificate on a shared file system, **`fsxadmin` privileges cannot fully revert it**. Use a dedicated file system, or agree on the residue in advance.

### 13.4 The target's root volume survives termination

After terminating the target instance, **one root EBS volume was left in `available`**. The launch template MGN created does not set `DeleteOnTermination` on it.

It is traceable from its tags. Because `AWSApplicationMigrationServiceManaged` and `AWSApplicationMigrationServiceSourceServerID` are present, **searching by source server ID surfaces anything left behind**.

This is separate from the staging and conversion volumes being deleted automatically in 12.10. **The migration target's root volume remains even after the instance is gone.**

### 13.5 Deliberately retained

| Retained | Reason |
|---|---|
| 8 MGN service roles and the service-linked role | No charge, and they save re-creating everything if MGN is reused |
| The 4 pre-existing client-ca certificates | Not created here |
| The shared file system and the 4 SVMs of other workstreams | Out of scope; `AVAILABLE` and all 4 SVMs confirmed intact after deletion |
| The secret (deleted with a 7-day recovery window) | Not an immediate deletion; it disappears after 7 days. A zero-day window is available but makes accidental deletion unrecoverable |

### 13.6 Post-teardown balance check

A delete call returning success is not evidence that the object was deleted. Everything was cross-checked after a 45-second wait.

| Item | Result |
|---|---|
| Three EC2 instances (source / target / replication server) | All `terminated` |
| EBS volumes in `available` | 0 |
| MGN source servers | 0 |
| Replication template `storageType` | `EBS` (no reference to the deleted SVM) |
| NLB / target group / VPC endpoint service | All 0 |
| Verification SVM | Does not exist |
| Launch template / two security groups / IAM role | All `NotFound` |
| **Shared file system** | **`AVAILABLE` (intact)** |
| **Other workstreams' SVMs** | **All 4 still present** |

---

## 14. References

Primary sources only.

### AWS Transform

- [What's New: AWS Transform announces general availability of Amazon FSx for NetApp ONTAP support](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)
- [AWS Transform Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html) — the 2026-08-30 entry
- [Document history for the AWS Transform User Guide](https://docs.aws.amazon.com/transform/latest/userguide/doc-history.html) — August 30, 2026
- [Supported Regions for AWS Transform](https://docs.aws.amazon.com/transform/latest/userguide/regions.html)

### AWS Transform MGN

- [FSx for ONTAP configuration](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html) — setup steps, Known limitations, Prerequisites
- [MGN Release notes](https://docs.aws.amazon.com/mgn/latest/ug/mgn-release-notes.html) — August 2026
- [What Is AWS Transform MGN?](https://docs.aws.amazon.com/mgn/latest/ug/what-is-mgn.html) — supported Regions
- [Storage related FAQs](https://docs.aws.amazon.com/mgn/latest/ug/Storage-Related-FAQ.html) — target storage types
- [Does MGN work with...?](https://docs.aws.amazon.com/mgn/latest/ug/does-mgn.html) — data flow with FSx for ONTAP

### Blogs

- [Migrate VMware Storage to Amazon FSx for NetApp ONTAP using AWS Transform (AWS Storage Blog)](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/)
- [Multi-Region Migration using AWS Application Migration Service (AWS Architecture Blog)](https://aws.amazon.com/blogs/architecture/multi-region-migration-using-aws-application-migration-service/) — states Amazon EC2 among source types
- [Automating FSx for NetApp ONTAP Mounts with SSM and MGN Post-Migration](https://aws.amazon.com/blogs/migration-and-modernization/automating-fsx-for-netapp-ontap-mounts-with-ssm-and-mgn-post-migration/)

### Amazon EVS (datastore path — separate capability)

- [Run high-performance workloads with Amazon FSx for NetApp ONTAP (EVS User Guide)](https://docs.aws.amazon.com/evs/latest/userguide/fsx-ontap.html)
- [What's New: Amazon EVS now integrates with Amazon FSx for NetApp ONTAP](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-elastic-vmware-service-fsx-netapp-ontap/) — states public preview
- [Using Amazon Elastic VMware Service with FSx for ONTAP (FSx User Guide)](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/evs-ontap.html)

### Related repositories

- [FSx for ONTAP Adoption Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook) — the coordination target in Section 10
- [Migration method comparison (this repository)](./migration-method-comparison.md)
- [AWS Transform migration procedure (this repository)](./aws-transform-migration-procedure.md)

---

*This report is based on public documentation as of 2026-09-04 and hands-on checks in a verification account (ap-northeast-1). Console initialization and certificate authentication, saving `FSX_ONTAP` onto the replication template, and everything from running replication through cutover, Finalize, and teardown were measured (Sections 12 and 13). What remains unverified is in Section 11.*
