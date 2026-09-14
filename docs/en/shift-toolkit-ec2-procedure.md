# Shift Toolkit — VMware ESXi → EC2 + FSx for ONTAP Migration Procedure

**Status**: Early Preview  
**Source**: Official procedure "Migrate VMs from VMware to AWS EC2 and FSx for ONTAP — Shift UI" (2026-06)  
**Last Updated**: 2026-06-22

> **Note**: The VMware ESXi to AWS EC2 migration path in Shift Toolkit is an Early Preview feature.
> Specifications, constraints, and support scope may change. Enablement requires contact with NetApp support.

---

## 1. Architecture Overview

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                        On-Premises                                        │
│  ┌─────────────┐     ┌──────────────────────────┐                        │
│  │ VMware ESXi │     │  ONTAP Cluster           │                        │
│  │  (vCenter)  │     │  ┌────────────────────┐  │                        │
│  │             │────▶│  │ NFS Volume (VMDKs) │  │                        │
│  │  Guest VMs  │     │  └────────────────────┘  │                        │
│  └─────────────┘     └──────────┬───────────────┘                        │
│                                 │ SnapMirror                              │
│  ┌──────────────────────┐       │                                        │
│  │ Shift Toolkit (Win)  │       │                                        │
│  │  - GUI / REST API    │       │                                        │
│  └──────────────────────┘       │                                        │
└─────────────────────────────────┼────────────────────────────────────────┘
                                  │ VPN / Direct Connect
┌─────────────────────────────────┼────────────────────────────────────────┐
│                        AWS VPC  │                                         │
│                                 ▼                                         │
│  ┌──────────────────────────────────────────────────┐                    │
│  │  Amazon FSx for NetApp ONTAP                     │                    │
│  │  ┌─────────────────────────────────────────┐     │                    │
│  │  │ SnapMirror Destination Volume (R/W化)   │     │                    │
│  │  │  - Boot VMDK → RAW → S3 → AMI          │     │                    │
│  │  │  - Data VMDKs → iSCSI LUNs             │     │                    │
│  │  └─────────────────────────────────────────┘     │                    │
│  └──────────────────────────────┬───────────────────┘                    │
│                             │ iSCSI (port 3260)                           │
│  ┌──────────────────────────▼───────────────────────┐                    │
│  │  Amazon EC2 Instance                             │                    │
│  │  ┌───────────────────┐  ┌──────────────────────┐│                    │
│  │  │ OS: EBS (gp3)     │  │ Data: FSx for ONTAP  ││                    │
│  │  │ (AMI からブート)   │  │ (iSCSI マルチパス)   ││                    │
│  │  └───────────────────┘  └──────────────────────┘│                    │
│  └──────────────────────────────────────────────────┘                    │
│                                                                           │
│  ┌────────────┐  ┌─────────────┐                                         │
│  │ S3 Bucket  │  │ IAM / SSM   │                                         │
│  │ (staging)  │  │ (vmimport)  │                                         │
│  └────────────┘  └─────────────┘                                         │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Prerequisites

### 2.0 Supported Guest Operating Systems

Before migration, verify that the source VM's guest OS is included in the following support matrix.

| OS | Supported Versions | Notes |
|----|-------------------|-------|
| **Windows Server** | 2016 / 2019 / 2022 / 2025 | 64-bit only |
| **Windows Desktop** | 10 / 11 | 64-bit only |
| **RHEL** | 7.2+ / 8.x / 9.x | SELinux enforcing supported |
| **CentOS** | 7.x | EOL note (ended 2024-06) |
| **AlmaLinux** | 7.x / 8.x / 9.x | CentOS alternative |
| **Rocky Linux** | 8.x / 9.x | CentOS alternative |
| **Ubuntu** | 18.04 / 22.04 / 24.04 | LTS only |
| **Debian** | 12 | — |
| **SUSE Linux Enterprise** | 12 / 15 | — |

> **Not supported (migration not possible):**
> - Windows Server 2008 / 2012 (officially unsupported; some success reports exist but automatic IP configuration is not available)
> - RHEL / CentOS 5.x / 6.x
> - All 32-bit operating systems
> - Non-Linux/Windows OS such as FreeBSD / Solaris

<!-- TODO: スクリーンショット — Shift Toolkit UI のサポート OS 選択画面 -->

### 2.1 VM Requirements

| Requirement | Details |
|-------------|---------|
| VMDK placement | On an **NFSv3** volume (all VMDKs for the same VM must reside in the same volume) |
| VMware Tools | Running on the guest VM (required during the preparation phase) |
| VM state (preparation) | RUNNING state |
| VM state (migration) | **POWERED OFF** (graceful shutdown before triggering migration) |
| NFSv4 | Not supported (will not appear in UI) |
| SAN-based | Must be relocated to an NFS datastore via Storage vMotion beforehand |

### 2.2 Storage Requirements

| Requirement | Details |
|-------------|---------|
| SnapMirror | Replication configured and healthy between the source NFS volume and FSx for ONTAP |
| FSx for ONTAP | Provisioned within the designated VPC |
| Network connectivity | Connection established between on-premises and AWS VPC (Direct Connect or VPN) |

### 2.3 AWS-Side Preparation

#### IAM Policy (vmimport role)

> **Production hardening recommended**: The following policy is intended for Early Preview / PoC configurations. For production environments, narrow `Resource: "*"` to specific ARNs and further restrict with condition keys (`aws:RequestedRegion`, `ec2:ResourceTag`, etc.).
>
> **Note**: The policy below is transcribed directly from the official procedure. It does not include `s3:PutObject` (needed for RAW → S3 upload), suggesting Shift Toolkit may use a separate authentication path (e.g., the Shift Toolkit VM's own IAM Role / Instance Profile) for S3 multipart uploads. Verify during hands-on testing and add permissions if needed.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3BucketAccess",
      "Effect": "Allow",
      "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::<BUCKET_NAME>"]
    },
    {
      "Sid": "S3ObjectAccess",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::<BUCKET_NAME>/*"]
    },
    {
      "Sid": "EC2MigrationActions",
      "Effect": "Allow",
      "Action": [
        "ec2:CopySnapshot",
        "ec2:RegisterImage",
        "ec2:ModifySnapshotAttribute",
        "ec2:DescribeSnapshots",
        "ec2:DescribeSnapshotAttribute",
        "ec2:DescribeImages",
        "ec2:DescribeImportSnapshotTasks",
        "ec2:DescribeInstances",
        "ec2:DescribeRegions"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Rationale for `Resource: "*"` and production guidance:**
>
> - `ec2:Describe*` actions do not support resource-level permissions, so `"*"` is mandatory. **Cited rather than asserted "per AWS specifications"**: IAM's [policy troubleshooting guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot_policies.html) states that none of the `ec2:Describe` actions support resource-level permissions. **For any individual action, check the Resource types column in the [service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html).**
> - For production, scope `ec2:CopySnapshot` / `ec2:RegisterImage` / `ec2:ModifySnapshotAttribute` as follows:
>
> ```json
> {
>   "Sid": "EC2MutationActionsScoped",
>   "Effect": "Allow",
>   "Action": [
>     "ec2:CopySnapshot",
>     "ec2:RegisterImage",
>     "ec2:ModifySnapshotAttribute"
>   ],
>   "Resource": [
>     "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:snapshot/*",
>     "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:image/*"
>   ],
>   "Condition": {
>     "StringEquals": {
>       "aws:RequestedRegion": "<REGION>"
>     }
>   }
> }
> ```
>
> - **Credential best practices**: Instead of entering long-term Access Keys into Shift Toolkit, consider using IAM roles + AssumeRole (temporary credentials). For AssumeRole from on-premises, options include IAM Identity Center OIDC federation or `sts:AssumeRole` with an external ID. While the Early Preview requires Access Keys, apply a rotation policy (within 90 days) and immediately disable them after migration is complete.
>
> **AssumeRole configuration example (for production):**
>
> 1. Grant only `sts:AssumeRole` to a dedicated migration IAM user (no direct EC2/S3 permissions)
> 2. Attach the above policy (EC2MigrationActions + S3) to a migration IAM role
> 3. Require External ID in the role's trust policy:
>
> ```json
> {
>   "Version": "2012-10-17",
>   "Statement": [{
>     "Effect": "Allow",
>     "Principal": { "AWS": "arn:aws:iam::<ACCOUNT_ID>:user/shift-migration-user" },
>     "Action": "sts:AssumeRole",
>     "Condition": {
>       "StringEquals": { "sts:ExternalId": "<UNIQUE_EXTERNAL_ID>" }
>     }
>   }]
> }
> ```
>
> 4. If Shift Toolkit does not natively support AssumeRole, use a wrapper script to obtain temporary credentials and inject them as environment variables:
>
> ```powershell
> # PowerShell: Obtain temporary credentials → set environment variables
> $creds = aws sts assume-role `
>   --role-arn "arn:aws:iam::<ACCOUNT_ID>:role/ShiftMigrationRole" `
>   --role-session-name "shift-migration" `
>   --external-id "<UNIQUE_EXTERNAL_ID>" `
>   --query "Credentials" --output json | ConvertFrom-Json
> $env:AWS_ACCESS_KEY_ID = $creds.AccessKeyId
> $env:AWS_SECRET_ACCESS_KEY = $creds.SecretAccessKey
> $env:AWS_SESSION_TOKEN = $creds.SessionToken
> # Validity: default 1 hour (extendable up to 12 hours with --duration-seconds)
> ```
>
> **Lifecycle management:**
> - Create dedicated user/role at project start
> - Immediately disable and delete the IAM user's Access Keys after migration is complete
> - Decide whether to retain the migration role for subsequent DR testing or delete it

#### Security Groups

> **Design principle**: Restrict security group sources to the minimum necessary. Never use `0.0.0.0/0`. Use SG-to-SG references to avoid hardcoding IP addresses directly.

**SG 1 — EC2 Instance (migrated VM) — Inbound:**

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP/SSH | `<SHIFT_TOOLKIT_IP>/32` | Linux post-launch verification from Shift Toolkit |
| 3389 | TCP/RDP | `<SHIFT_TOOLKIT_IP>/32` | Windows post-launch verification from Shift Toolkit |
| 5986 | TCP/WinRM-HTTPS | `<SHIFT_TOOLKIT_IP>/32` | iSCSI initiator configuration (HTTPS only recommended) |
| ICMP | — | `<SHIFT_TOOLKIT_IP>/32` | Boot confirmation ping |

> **Production recommendation**: Restrict WinRM to port 5986 (HTTPS) only; do not open 5985 (HTTP). Pre-configure certificates. If using 5985 in a PoC environment, explicitly mark it as a temporary measure.

**SG 2 — FSx for ONTAP ENI + VPC Endpoints — Inbound:**

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 3260 | TCP/iSCSI | SG 1 (EC2 instance SG) | EC2 → FSx for ONTAP data LUN mount |
| 443 | TCP/HTTPS | SG 1 + `<SHIFT_TOOLKIT_IP>/32` | ONTAP REST API (from Shift Toolkit + EC2) |
| 22 | TCP/SSH | `<SHIFT_TOOLKIT_IP>/32` | VMDK→RAW conversion via ONTAP CLI |
| 11104-11105 | TCP | `<ON_PREM_ONTAP_IP>/32` | SnapMirror replication (from source ONTAP) |
| ICMP | — | SG 1 + `<SHIFT_TOOLKIT_IP>/32` | Health check |

> **Note**: `<SHIFT_TOOLKIT_IP>` is the IP address of the on-premises Shift Toolkit Windows VM. It must be able to reach the VPC via VPN/Direct Connect.
> **Note**: Restrict the source for SnapMirror ports (11104-11105) to the IP address of the on-premises ONTAP cluster's intercluster LIFs.

#### Other

- S3 bucket (staging for VM Import/Export)
- SSM instance profile (IAM instance profile ARN)
- Key pair (for EC2 login)

### 2.4 Shift Toolkit Enablement

1. Contact the NetApp support alias (address given in the Shift Toolkit v8.0 blog) to enable the EC2 Early Preview
2. Edit `config.json` in the Shift Toolkit installation directory:
   ```json
   { "enableAmazonEC2": true }
   ```
3. Restart the NetApp Shift service

---

## 3. Migration Procedure

### Phase 1: Site Registration

1. Log in to the Shift Toolkit UI
2. Select **Add New Site** → **Destination**
3. Enter the following:
   - Site Name: any descriptive name
   - Hypervisor: **AWS EC2**
   - Site Location / Connector: default
4. Enter AWS credentials:
   - Credential Name
   - AWS Access Key ID
   - AWS Secret Access Key
   - Region selection
5. Enter FSx for ONTAP connection information
6. Click **Create Site**

<!-- TODO: スクリーンショット — Add New Site > AWS EC2 選択画面 -->
<!-- TODO: スクリーンショット — AWS Credential / FSx for ONTAP 入力画面 -->

### Phase 2: Resource Group Creation

1. Navigate to **Resource Groups** → **Create New Resource Group**
2. Select the source site → **Create**
3. Select workflow: **Clone based Migration** (end-to-end migration)
4. Select VMs for migration (use Datastore filter to select NFSv3 datastores)
5. Configure Destination Site / AWS Entry / Datastore-to-Volume mapping
6. Set Boot Order / Boot Delay (default: 3)
7. Click **Create Resource Group**

<!-- TODO: スクリーンショット — Resource Group 作成画面（VM 選択 + Datastore フィルター） -->

> **Note**: It is recommended to move migration target VMs to a **dedicated SVM/datastore** separate from the production NFS datastore beforehand (for production workload isolation).

### Phase 3: Blueprint Creation

1. Navigate to **Blueprints** → **Create New Blueprint**
2. Enter Blueprint name + source/destination mapping
3. Specify S3 bucket (for VM Import/Export workflow)
4. Select Resource Group → **Continue**
5. Set Execution Order (for multiple resource groups)
6. Network Mapping (VPC subnet/VLAN mapping)
7. Storage Mapping (auto-selected)
8. **VM Details configuration**:
   - Service account (Linux: sudoers, Windows: local administrator)
   - EC2 settings: Security Group / Key Pair / IAM Instance Profile
   - IP settings: DHCP or Static
   - VM resize (CPU/RAM → appropriate instance type auto-selected)
9. Schedule configuration (optional: specify a date/time at least 30 minutes in the future)
10. Click **Create Blueprint**

<!-- TODO: スクリーンショット — Blueprint 作成画面（Network Mapping + VM Details） -->
<!-- TODO: スクリーンショット — EC2 設定（Security Group / Key Pair / Instance Profile） -->

> **Current Preview constraint**: prepareVM (automated guest OS preparation injection) is disabled. It will be enabled in the next build. Manual pre-preparation is required at this time (see Section 4).

### Phase 4: Migration Execution

**Prerequisite**: VM must be gracefully shut down.

Click the **Migrate** button (or wait for the scheduled time for automatic execution). The following steps execute automatically:

```text
 1. Delete all VMware snapshots (target VM)
 2. Create new VMware snapshot (per Resource Group)
 3. Create source ONTAP volume snapshot
 4. SnapMirror update (push final delta)
 5. SnapMirror break (make FSx for ONTAP side R/W)
 6. Boot disk: VMDK → RAW conversion
 7. Boot RAW → S3 upload
 8. Boot disk → AMI registration (AWS VM Import/Export)
 9. Data disk: VMDK → LUN conversion (on FSx for ONTAP)
10. iSCSI target preparation:
    - Create/reuse igroup
    - LUN → igroup mapping (deterministic LUN ID)
    - Discover SVM target IQN
    - Detect guest OS (Linux/Windows)
11. Launch EC2 instance (boot from AMI)
12. iSCSI connection within EC2 guest (mount data disks)
```

> **Note**: Source-side VMware snapshots and ONTAP snapshots are retained as recovery references.

### Downtime Composition and Duration Estimates

The VM downtime during migration is the sum of the following components. **Assuming SnapMirror pre-replication is complete**, the majority of the cutover window consists of "final delta + OS disk conversion + EC2 launch."

#### Downtime Components

```text
|←─── Downtime start (VM shutdown) ─────────────────────── EC2 launch complete ───→|

[1] VM graceful shutdown                                    : 1-3 min
[2] VMware snapshot delete + new creation                   : 1-2 min
[3] ONTAP volume snapshot                                   : < 1 min
[4] SnapMirror final update (delta only)                    : 1-10 min *
[5] SnapMirror break                                        : < 1 min
[6] Boot disk: VMDK → RAW conversion                        : 5-30 min **
[7] Boot RAW → S3 upload                                    : 5-60 min ***
[8] S3 → AMI registration (import-image)                    : 10-45 min ****
[9] Data disk: VMDK → LUN conversion                        : 1-5 min (FlexClone-based)
[10] iSCSI target preparation                               : < 1 min
[11] EC2 instance launch                                    : 1-3 min
[12] iSCSI connection + data disk mount                     : 2-5 min
─────────────────────────────────────────────────────────────────────────────
Total estimate                                               : 30 min – 2.5 hours
```

> **\*** SnapMirror final update: Depends on the amount of changed data after VM shutdown. If continuous replication has been running, the delta is minimal (changed blocks only).
>
> **\*\*** VMDK → RAW conversion: Conversion via ONTAP CLI. Depends on disk size and ONTAP backend performance.
>
> **\*\*\*** S3 upload: Strongly depends on network bandwidth. Significant difference between VPN and Direct Connect. Upload from FSx for ONTAP to S3 in the same region uses the AWS internal network and is faster.
>
> **\*\*\*\*** import-image: AWS internal processing. Depends on size and region congestion. Not controllable.

#### Duration Estimates by VMDK Size

The following are **estimates** and will vary depending on environment (network bandwidth, ONTAP performance, AWS region load). Verify with hands-on testing.

| Boot VMDK Size | RAW Conversion | S3 Upload | import-image | Total (Boot only) |
|---------------|----------------|-----------|-------------|-------------------|
| 30 GB | 3-5 min | 3-10 min | 10-20 min | ~20-35 min |
| 50 GB | 5-10 min | 5-15 min | 15-25 min | ~25-50 min |
| 100 GB | 10-20 min | 10-30 min | 20-35 min | ~40-85 min |
| 200 GB | 20-30 min | 20-60 min | 30-45 min | ~70-135 min |

| Data VMDK Size | LUN Conversion | iSCSI Prep | Notes |
|---------------|----------------|------------|-------|
| Any (up to several TB) | 1-5 min | < 1 min | FlexClone-based, so **nearly independent of size** |

> **Important**: Data disk LUN conversion is a FlexClone/metadata operation, so even 1TB completes in minutes. The dominant factor in downtime is **OS disk S3 upload + import-image**.

#### Recommendations for Reducing Downtime

1. **Keep the boot disk small**: OS + minimal applications only. Place large data on data disks (FSx for ONTAP LUNs)
2. **Run SnapMirror pre-sync sufficiently**: Minimize the delta before cutover
3. **Use Direct Connect**: More stable and faster S3 upload speeds compared to VPN
4. **Wait for EBS Direct API (next drop)**: Will eliminate S3 staging, significantly shortening steps 7-8
5. **Schedule the migration window for off-peak hours**: AWS internal processing speed for import-image is affected by region load

---

## 4. Guest OS Pre-Preparation (Current Preview — Manual)

In the current Preview version, `prepareVM` is disabled, so the following must be performed manually.

### 4.1 Linux (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install -y cloud-init cloud-guest-utils chrony
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_ec2.cfg <<EOF
datasource_list: [ Ec2, None ]
datasource: { Ec2: { strict_id: false, timeout: 30, max_wait: 60 } }
EOF'
sudo systemctl enable --now chrony
sudo systemctl enable cloud-init-local cloud-init cloud-config cloud-final
```

### 4.2 Linux (RHEL / CentOS / AlmaLinux / Rocky Linux)

```bash
# cloud-init installation (RHEL 8+ / AlmaLinux 8+ / Rocky 8+)
sudo dnf install -y cloud-init cloud-utils-growpart chrony

# iSCSI initiator (required for FSx for ONTAP data disk connection after migration)
sudo dnf install -y iscsi-initiator-utils device-mapper-multipath
sudo systemctl enable iscsid multipathd

# For RHEL 7 / CentOS 7, use yum instead
# sudo yum install -y cloud-init cloud-utils-growpart chrony iscsi-initiator-utils device-mapper-multipath

# EC2 datasource configuration
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_ec2.cfg <<EOF
datasource_list: [ Ec2, None ]
datasource: { Ec2: { strict_id: false, timeout: 30, max_wait: 60 } }
EOF'

# NTP configuration (Chrony)
sudo systemctl enable --now chronyd

# Enable cloud-init services
sudo systemctl enable cloud-init-local cloud-init cloud-config cloud-final

# (Recommended) Enable NetworkManager and allow cloud-init to manage network configuration
sudo systemctl enable NetworkManager

# (Recommended) Disable ifcfg legacy scripts (RHEL 8+)
# Prevents conflicts with cloud-init network configuration management
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_network.cfg <<EOF
network:
  config: disabled
EOF'
```

> **RHEL-specific notes:**
> - RHEL 7 series uses `yum`. `dnf` is available on RHEL 8 and later.
> - If SELinux is enforcing, verify that cloud-init contexts are correctly set: `restorecon -Rv /etc/cloud/`
> - Package installation will fail if RHEL subscription registration is not active. Verify subscription status before migration.
> - CentOS Stream 9 / AlmaLinux 9 / Rocky Linux 9 work as-is with the above commands.

### 4.3 Linux (SUSE/openSUSE)

```bash
VER=$( . /etc/os-release; echo $VERSION_ID )
sudo zypper addrepo --refresh \
  "http://download.opensuse.org/distribution/leap/$VER/repo/oss/" repo-oss
sudo zypper addrepo --refresh \
  "http://download.opensuse.org/distribution/leap/$VER/repo/non-oss/" repo-non-oss
sudo zypper addrepo --refresh \
  "http://download.opensuse.org/update/leap/$VER/oss/" repo-update
sudo zypper --gpg-auto-import-keys refresh
sudo zypper --non-interactive install \
  cloud-init cloud-init-config-suse growpart chrony curl
sudo bash -c 'cat >/etc/cloud/cloud.cfg.d/99_ec2.cfg <<EOF
datasource_list: [ Ec2, None ]
datasource: { Ec2: { strict_id: false, timeout: 30, max_wait: 60 } }
EOF'
sudo systemctl enable --now chronyd
sudo systemctl enable cloud-init-local cloud-init cloud-config cloud-final
```

### 4.4 Windows

PowerShell (Administrator):

```powershell
$tmp = $env:TEMP
Invoke-WebRequest `
  'https://s3.amazonaws.com/amazon-ec2launch-v2/windows/amd64/latest/AmazonEC2Launch.msi' `
  -OutFile "$tmp\EC2Launch.msi" -UseBasicParsing
Start-Process msiexec.exe -ArgumentList "/i","$tmp\EC2Launch.msi","/quiet" -Wait
```

### 4.5 Preparation Script Locations

| OS | Path |
|----|------|
| Windows | `C:\NetApp` |
| Linux | `/NetApp` and `/opt` |

---

## 5. Post-Migration Verification

### 5.1 EC2 Instance Verification

- Confirm normal boot from AMI
- Verify network settings (IP address) are as expected
- Confirm SSM Agent connectivity is available

### 5.2 iSCSI Data Disk Verification

- Verify session with `iscsiadm -m session` (Linux) or iSCSI Initiator (Windows)
- Confirm data disks are mounted and data is consistent
- Verify I/O performance meets expectations

### 5.3 iSCSI Multipath Configuration

FSx for ONTAP (Multi-AZ) supports ALUA (Asymmetric Logical Unit Access), providing preferred and non-preferred paths. Multipath configuration from EC2 instances improves availability and throughput.

#### Linux (dm-multipath)

```bash
# 1. Confirm multipath is installed (done in Section 4.2)
sudo systemctl status multipathd

# 2. Create /etc/multipath.conf with ONTAP recommended settings
sudo bash -c 'cat >/etc/multipath.conf <<EOF
defaults {
    find_multipaths yes
    user_friendly_names yes
}

devices {
    device {
        vendor                "NETAPP"
        product               "LUN.*"
        path_grouping_policy  group_by_prio
        path_selector         "service-time 0"
        path_checker          tur
        features              "3 queue_if_no_path pg_init_retries 50"
        prio                  ontap
        failback              immediate
        no_path_retry         queue
    }
}
EOF'

# 3. Restart multipathd to apply configuration
sudo systemctl restart multipathd

# 4. Discover iSCSI targets and log in
sudo iscsiadm -m discovery -t sendtargets -p <FSXN_ISCSI_IP>
sudo iscsiadm -m node --login

# 5. Verify multipath devices
sudo multipath -ll
```

> **Expected output example:**
> ```
> mpath0 (3600a09...) dm-2 NETAPP,LUN C-Mode
> size=100G features='3 queue_if_no_path pg_init_retries 50' hwhandler='0' wp=rw
> |-+- policy='service-time 0' prio=50 status=active
> | `- 3:0:0:0 sdb 8:16 active ready running
> `-+- policy='service-time 0' prio=10 status=enabled
>   `- 4:0:0:0 sdc 8:32 active ready running
> ```

#### Windows (MPIO + iSCSI Initiator)

```powershell
# 1. Enable MPIO feature (may require restart)
Install-WindowsFeature -Name Multipath-IO -IncludeManagementTools
# If restart is required: Restart-Computer

# 2. Add iSCSI device to MPIO
New-MSDSMSupportedHW -VendorId "NETAPP" -ProductId "LUN C-Mode"
# Applied after restart: Restart-Computer

# 3. Set MPIO policy (round-robin recommended)
Set-MSDSMGlobalDefaultLoadBalancePolicy -Policy RR

# 4. Start iSCSI Initiator service
Set-Service -Name MSiSCSI -StartupType Automatic
Start-Service MSiSCSI

# 5. Connect to iSCSI target
New-IscsiTargetPortal -TargetPortalAddress <FSXN_ISCSI_IP>
Connect-IscsiTarget -NodeAddress <TARGET_IQN> -IsPersistent $true

# 6. Verification
Get-MSDSMAutomaticClaimSettings
Get-Disk | Where-Object { $_.BusType -eq "iSCSI" }
```

> **Note**: In FSx for ONTAP Multi-AZ configurations, the path to the preferred node has `prio=50` (Active/Optimized) and the path to the standby node has `prio=10` (Active/Non-Optimized). During failover, paths switch automatically.

### 5.4 ONTAP Feature Verification

- Verify that snapshots can be taken on LUNs on FSx for ONTAP
- Confirm FlexClone operates normally
- Verify Storage Efficiency (compression/deduplication) is enabled

---

## 6. Current Preview Constraints

| Item | Constraint | Future Plans |
|------|-----------|--------------|
| OS disk conversion method | S3 Import/Export only | EBS Direct APIs to be enabled in the next drop |
| prepareVM auto-execution | Disabled | To be enabled in the next build |
| VMware Tools auto-removal | Shown as disabled in UI | To be enabled in the next build |
| ENA driver auto-injection | Included in prepareVM but disabled | Same as above |

---

## 7. PoC Cost Estimate

The following is an approximate estimate for **running 1 VM (Boot 50GB + Data 200GB) in the Tokyo region for 1 month**. Temporary costs during the migration period and ongoing costs are presented separately.

> **Note**: Prices are estimates based on published pricing for the Tokyo region (ap-northeast-1) as of 2026-06. Verify the latest prices using the [AWS Pricing Calculator](https://calculator.aws/).

### 7.1 One-Time Migration Costs (Migration Window Only)

| Resource | Sizing | Unit Price | Quantity | Cost |
|----------|--------|-----------|----------|------|
| S3 storage (Boot RAW staging) | 50 GB × few hours | $0.025/GB-month | 50 GB × 0.01 month | ~$0.01 |
| S3 PUT/GET requests | Multipart upload | $0.0047/1000 req | ~100 req | ~$0.01 |
| Data transfer (S3 → EC2 same region) | — | $0 | — | $0 |

**Total one-time migration cost: ~$0.02 (negligible)**

### 7.2 Ongoing Monthly Costs (Post-Migration Operations)

| Resource | Sizing | Unit Price (Tokyo) | Monthly Cost |
|----------|--------|-------------------|--------------|
| **EC2 instance** | m5.large (2 vCPU, 8 GiB) | $0.124/hr | ~$90 |
| **EBS gp3** (Boot) | 50 GB, 3000 IOPS, 125 MB/s | $0.096/GB-month | ~$4.80 |
| **FSx for ONTAP** (SSD) | 200 GB provisioned | $0.252/GB-month | ~$50.40 |
| **FSx for ONTAP** throughput | 128 MB/s | $0.583/MB/s-month | ~$74.62 |
| **EBS Snapshot** (AMI retention) | 50 GB (full first month, incremental thereafter) | $0.05/GB-month | ~$2.50 |

**PoC monthly total: ~$222/month (1 VM)**

### 7.3 Cost Optimization Points

| Aspect | Recommendation |
|--------|---------------|
| EC2 | Use Spot Instances or scheduled start/stop during PoC to reduce runtime hours |
| FSx for ONTAP | Use Single-AZ for PoC to reduce costs by ~40%. Use Multi-AZ for production |
| FSx for ONTAP Storage Efficiency | Compression + deduplication typically achieves 30-50% effective usage reduction |
| FSx for ONTAP capacity pool | Automatically tier infrequently accessed data at $0.0252/GB-month |
| S3 staging | Delete immediately after migration (no retention needed) |
| EBS Snapshot | Periodically delete unnecessary AMIs / Snapshots |

> **distinction discipline**: The above are estimates based on sample sizing. Actual costs will vary depending on instance type, Storage Efficiency effectiveness, uptime, and data growth. For production estimates, use [AWS Pricing Calculator](https://calculator.aws/) + FSx for ONTAP sizing tool.

---

## 8. EBS Direct API Workflow (Next Drop — Preview)

The EBS Direct API method to be enabled in the next drop bypasses S3 staging and directly creates an EBS snapshot for the OS disk. The only change in workflow is the OS disk creation method; the data disk process (LUN conversion + iSCSI attach) remains identical.

**Benefits of EBS Direct API:**

- No S3 upload required → reduced transfer time
- Enables snapshot creation across regions/AZs/accounts
- Positioned as the recommended approach

---

## 9. Rollback Procedure

The following describes recovery procedures when failures occur at various stages of migration. The fundamental principle is: "**As long as the source VM and source ONTAP snapshots are intact, you can always revert to the source.**"

### 9.1 Rollback Decision Flow

```text
Migration failure detected
  │
  ├─ Failure at Phase 4 steps 1-5 (up to SnapMirror break)
  │   → Source VM unchanged. Recover with SnapMirror resync (9.2)
  │
  ├─ Failure at Phase 4 steps 6-8 (Boot disk conversion / S3 / AMI)
  │   → FSx for ONTAP side is R/W but data is intact
  │   → Delete S3 objects / snapshots / AMI, then SnapMirror resync (9.3)
  │
  ├─ Failure at Phase 4 steps 9-10 (Data disk LUN conversion / iSCSI)
  │   → AMI registered but EC2 not launched or launched with missing data disks
  │   → Deregister AMI + delete LUNs + SnapMirror resync (9.4)
  │
  └─ Failure at Phase 4 steps 11-12 (EC2 launch / iSCSI connection)
      → Terminate EC2 instance + unmap LUNs + SnapMirror resync (9.5)
```

### 9.2 Failure Before SnapMirror Break (Least Severe)

No changes to the source environment. SnapMirror on the FSx for ONTAP side remains healthy.

**Resolution**: Identify root cause → re-execute. No special recovery operations needed.

### 9.3 Failure During Boot Disk Conversion / S3 Upload / AMI Registration

SnapMirror is already broken (FSx for ONTAP is R/W).

```bash
# 1. Delete intermediate files from S3 bucket
aws s3 rm s3://<BUCKET_NAME>/<VM_NAME>/ --recursive

# 2. Cancel incomplete import-image task (if task ID is available)
aws ec2 cancel-import-task --import-task-id import-snap-xxxxxxxxx

# 3. Delete incomplete AMI / snapshot (if registered)
aws ec2 deregister-image --image-id ami-xxxxxxxxx
aws ec2 delete-snapshot --snapshot-id snap-xxxxxxxxx

# 4. Resync SnapMirror on the FSx for ONTAP side (revert to source)
# ONTAP CLI (FSx for ONTAP side):
snapmirror resync -destination-path <SVM_NAME>:<VOLUME_NAME>
```

> **Note**: `snapmirror resync` discards changes on the destination and resumes synchronization with the source. Intermediate data from the conversion process is lost, but the source remains intact.
>
> **Estimated duration**: Resync is not a baseline retransfer but a **delta transfer** (incremental from common snapshot). Depends on the amount of data written after break during the migration flow (intermediate files from VMDK→RAW conversion, etc.), but is typically much shorter than the original full SnapMirror initialization. Estimate: 10-30 minutes for 100GB of changes (depends on network bandwidth).

### 9.4 Failure During Data Disk LUN Conversion

Boot disk was successfully converted to AMI, but data disk LUN conversion stalled midway.

```bash
# 1. Deregister the created AMI
aws ec2 deregister-image --image-id ami-xxxxxxxxx
aws ec2 delete-snapshot --snapshot-id snap-xxxxxxxxx

# 2. Delete incomplete LUNs on FSx for ONTAP
# ONTAP CLI:
lun show -vserver <SVM_NAME> -volume <VOLUME_NAME>
lun delete -vserver <SVM_NAME> -path /vol/<VOLUME_NAME>/<LUN_NAME>

# 3. Delete igroup if it was created
igroup show -vserver <SVM_NAME>
igroup delete -vserver <SVM_NAME> -igroup <IGROUP_NAME>

# 4. SnapMirror resync
snapmirror resync -destination-path <SVM_NAME>:<VOLUME_NAME>
```

### 9.5 Failure After EC2 Launch (iSCSI Connection Failure / Data Inconsistency)

EC2 launched but data disks are not properly mounted, or data inconsistency is detected.

```bash
# 1. Stop and terminate EC2 instance
aws ec2 terminate-instances --instance-ids i-xxxxxxxxx

# 2. Deregister AMI
aws ec2 deregister-image --image-id ami-xxxxxxxxx
aws ec2 delete-snapshot --snapshot-id snap-xxxxxxxxx

# 3. Offline and delete LUNs on FSx for ONTAP
# ONTAP CLI:
lun offline -vserver <SVM_NAME> -path /vol/<VOLUME_NAME>/<LUN_NAME>
lun delete -vserver <SVM_NAME> -path /vol/<VOLUME_NAME>/<LUN_NAME>
igroup delete -vserver <SVM_NAME> -igroup <IGROUP_NAME>

# 4. Resync SnapMirror to recover synchronization with source
snapmirror resync -destination-path <SVM_NAME>:<VOLUME_NAME>

# 5. Power on the source VM (recover on VMware)
# vCenter UI or PowerCLI:
# Start-VM -VM <VM_NAME>
```

### 9.6 Post-Rollback Verification Checklist

| Verification Item | Command / Method |
|-------------------|-----------------|
| SnapMirror is resynchronizing | `snapmirror show -destination-path <SVM>:<VOL>` → status: `Snapmirrored`, transfer-status: `Transferring` |
| Source VM starts normally | Verify VM Power State / VMware Tools heartbeat in vCenter UI |
| Source data is intact | Verify application consistency within the VM |
| AWS-side resources are cleaned up | `aws ec2 describe-images --owners self` / `aws ec2 describe-snapshots --owner-ids self` — no stale resources |
| S3 bucket is empty | `aws s3 ls s3://<BUCKET_NAME>/<VM_NAME>/` → empty |

### 9.7 Critical Notes for Rollback

- **Source VMware snapshots are retained**: VMware snapshots and ONTAP snapshots created by the migration workflow on the source side are preserved as "recovery references." If cleaning these up after rollback, manually delete them only after confirming data consistency.
- **SnapMirror resync direction**: Always specify `destination-path` (FSx for ONTAP side). Resyncing in the reverse direction will **overwrite source data**.
- **Partial success judgment**: If the boot disk was successfully converted to AMI and only some data disks failed, there is the option to leverage the successful portion and re-execute only the failed parts. However, at the Early Preview stage, full rollback → re-execution is recommended.
- **Rollback after production cutover**: After new data has been written on EC2, a simple "revert to source" rollback will result in data loss. Rollback after cutover decision requires separate planning (failback = reverse SnapMirror configuration).

---

## 10. Verification Results (2026-06)

### 10.1 Results Summary

| Blueprint | Configuration | Result | Notes |
|-----------|--------------|--------|-------|
| bp-winmigrate-test | Boot disk only (C drive only) | ✅ Migration Complete | Initial test. EBS only |
| bp01 | Multi-disk (boot + data) | ❌ Migration Error / Partially Healthy | Windows Firewall blocked SSM Agent / iSCSI |
| bp-ec2-migrate | Multi-disk (boot + data) | ✅ Active / Healthy | Succeeded after Firewall fix |

### 10.2 Measured Timing Data (bp-ec2-migrate)

Per-step durations from the completed migration job for Blueprint `bp-ec2-migrate`:

| Step | Processing | Duration |
|------|-----------|----------|
| 1 | Checking if a snapshot can be triggered on the volumes | 0.5 sec |
| 2 | Deleting existing snapshots for all VMs in the setup | 1.7 sec |
| 3 | Triggering VM snapshots for resource groups at source before disk upload | 30.2 sec |
| 4 | Triggering volume snapshots before disk conversion | 5.2 sec |
| 5 | Updating SnapMirror relationships — final sync to FSx for ONTAP | 70.5 sec |
| 6 | Breaking SnapMirror relationships | 2 min 40.5 sec |
| 7 | Converting boot disk VMDKs to RAW | 12.7 sec |
| 8 | Uploading boot disk RAW files to S3 | **68 min 5.1 sec** |
| 9 | Importing boot disks to AMIs | **36 min 20.6 sec** |
| 10 | Launching EC2 instances | 15.1 sec |

**Total: approximately 1 hour 49 minutes**

#### Analysis

- **S3 upload (68 min) and AMI import (36 min) account for 95% of total time**. These two steps dominate the downtime.
- SnapMirror-related steps (final sync + break) completed in approximately 3 min 51 sec total — very fast.
- VMDK → RAW conversion took 12.7 sec — fast due to being an ONTAP CLI metadata operation.
- **Shift Toolkit 8.1 (next version) plans to switch to EBS Direct API** → S3 upload + AMI import will be eliminated, with significant time reduction expected.

### 10.3 FSx for ONTAP Verification

After successful multi-disk migration, confirmed that iSCSI LUNs were properly created and mapped on FSx for ONTAP:

```text
FsxIdXXXXXXXXXXXXXXXXX::> lun show
Vserver   Path                            State   Mapped   Type        Size
--------- ------------------------------- ------- -------- -------- --------
fsxsvm01  /vol/ds_migtoaws_bk/win_testvm02-disk1-clone.lun
                                           online  mapped   linux        50GB
```

### 10.4 Multi-Disk Configuration Failure Root Cause and Workaround

The initial multi-disk configuration (bp01) failed due to:

| Failure Point | Root Cause | Workaround |
|--------------|-----------|------------|
| Disk attach from FSx for ONTAP | Windows Firewall blocked iSCSI / SSM Agent communication | Open required ports (3260, 443, ICMP) in Windows Firewall before migration |
| SSM Agent connection | Firewall + network path issues | Verify SG / Route Table allows SSM Agent to reach AWS after EC2 launch |

**Lessons for production:**

- In addition to guest OS preparation (Section 4), **Windows Firewall pre-configuration is mandatory**
- Pre-allow iSCSI ports (3260), SSM Agent (443 outbound), WinRM (5986)
- Check both Security Groups AND guest OS firewall

### 10.5 Planned Next Verifications

- [ ] Multi-disk configuration test with Linux VM
- [ ] Duration measurement with large disks (200GB+)
- [ ] Re-verification after Shift Toolkit 8.1 (EBS Direct API) release

---

## Related Documents

- [research-summary.md](./research-summary.md) — Research report summary
- [Shift Toolkit Overview (NetApp Official)](https://docs.netapp.com/us-en/netapp-solutions-virtualization/migration/shift-toolkit-overview.html)
- [What's New in Shift v8.0 Blog](https://community.netapp.com/t5/Tech-ONTAP-Blogs/What-s-New-in-Shift-v8-0-File-to-LUN-EC2-FSx-for-ONTAP-Trident-Integration-amp/ba-p/467669)
