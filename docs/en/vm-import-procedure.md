# Scenario B Procedure: Creating an AMI from an OS Disk Using VM Import/Export

**Purpose**: A backup plan for cases where the Shift Toolkit Early Preview does not cover OS disks (Scenario B).
This procedure transfers a VMware VMDK to AWS via S3 and registers it as an AMI.

> Reference: [AWS VM Import/Export Documentation](https://docs.aws.amazon.com/vm-import/latest/userguide/vmimport-image-import.html)

---

## Prerequisites

- AWS CLI v2 installed
- S3 bucket created (for VMDK upload)
- IAM role `vmimport` created (see [official instructions](https://docs.aws.amazon.com/vm-import/latest/userguide/required-permissions.html))
- Source VM in a stopped state
- Supported disk formats: VMDK, VHD, VHDX, RAW

---

## Procedure

Steps 1 through 6 run in order: export the VMDK, upload it to S3, run `import-image`, watch the progress, launch an EC2 instance from the resulting AMI, and verify it.

### Step 1: Export VMDK from VMware

```bash
# Export VMDK from vCenter / ESXi
# Method A: OVF export via vSphere Client → extract VMDK
# Method B: Copy using vmkfstools (ESXi SSH)
vmkfstools -i /vmfs/volumes/datastore1/vm-name/vm-name.vmdk \
  /vmfs/volumes/datastore1/export/vm-name-flat.vmdk -d thin
```

**Note**: The exported VMDK must be in "flat" (monolithic) format. Sparse disks are not supported by VM Import.

### Step 2: Upload to S3

```bash
# Upload to S3 bucket (use multipart for large files)
aws s3 cp ./vm-name-flat.vmdk s3://your-vmimport-bucket/imports/ \
  --region ap-northeast-1

# Verify upload
aws s3 ls s3://your-vmimport-bucket/imports/vm-name-flat.vmdk
```

### Step 3: Run import-image

```bash
# Create AMI using the import-image command
aws ec2 import-image \
  --description "VMware to EC2 migration - test-linux-01" \
  --disk-containers "Format=vmdk,UserBucket={S3Bucket=your-vmimport-bucket,S3Key=imports/vm-name-flat.vmdk}" \
  --region ap-northeast-1 \
  --license-type BYOL \
  --architecture x86_64 \
  --platform Linux

# Example response:
# {
#   "ImportTaskId": "import-ami-0123456789abcdef0",
#   "Status": "active",
#   ...
# }
```

**Parameter descriptions:**

- `--license-type`: `BYOL` (Bring Your Own License) or `AWS` (AWS-provided license)
- `--platform`: `Linux` or `Windows`
- `--architecture`: `x86_64` (use `arm64` for ARM)

### Step 4: Monitor Import Progress

```bash
# Check status (completion takes tens of minutes to several hours)
aws ec2 describe-import-image-tasks \
  --import-task-ids import-ami-0123456789abcdef0 \
  --region ap-northeast-1

# One-liner for periodic progress checks
watch -n 30 "aws ec2 describe-import-image-tasks \
  --import-task-ids import-ami-0123456789abcdef0 \
  --query 'ImportImageTasks[0].{Status:Status,Progress:Progress,StatusMessage:StatusMessage}' \
  --output table"
```

**Status transitions:**
`active` → `converting` → `updating` → `completed`

### Step 5: Launch an EC2 Instance from the AMI

```bash
# After import completes, retrieve the AMI ID
AMI_ID=$(aws ec2 describe-import-image-tasks \
  --import-task-ids import-ami-0123456789abcdef0 \
  --query 'ImportImageTasks[0].ImageId' \
  --output text)

echo "AMI ID: $AMI_ID"

# Launch an EC2 instance
aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type m5.large \
  --subnet-id subnet-xxxxxxxx \
  --security-group-ids sg-xxxxxxxx \
  --key-name your-key-pair \
  --region ap-northeast-1 \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=migrated-vm-01}]'
```

### Step 6: Post-Launch Verification

```bash
# Verify SSH connectivity
ssh -i your-key.pem ec2-user@<instance-ip>

# Verify drivers (for Nitro instances)
lsmod | grep ena          # ENA network driver
lsmod | grep nvme         # NVMe block device driver
cat /sys/class/dmi/id/bios_vendor  # Confirm running on AWS

# Verify networking
ip addr show
curl -s http://169.254.169.254/latest/meta-data/instance-id
```

---

## Automatic Modifications Performed by VM Import

AWS VM Import/Export automatically applies the following modifications during import:
(See [official documentation: Programmatic modifications](https://docs.aws.amazon.com/vm-import/latest/userguide/import-modify-vm.html))

- Installation of Citrix Xen / AWS PV drivers
- Installation of ENA drivers (for Nitro instance support)
- Boot loader modifications (GRUB, etc.)
- Network configuration adjustments (DHCP enablement)
- SSH server configuration verification
- Removal of VMware Tools

Specifying the `--no-modifications` flag skips these modifications, but this is not recommended.

---

## Additional Considerations for Windows

```bash
# For Windows
aws ec2 import-image \
  --description "Windows Server 2022 migration" \
  --disk-containers "Format=vmdk,UserBucket={S3Bucket=your-vmimport-bucket,S3Key=imports/win-vm.vmdk}" \
  --region ap-northeast-1 \
  --license-type BYOL \
  --platform Windows
```

- For BYOL: Separate activation via KMS server or MAK key is required
- For License Included: Specify `--license-type AWS` (AWS license is applied)
- Windows Server 2008 is not supported by VM Import

---

## Troubleshooting

| Error | Cause | Resolution |
|-------|-------|------------|
| `ClientError: Unsupported image format` | Sparse VMDK specified | Re-export in flat/monolithic format |
| `ClientError: Invalid S3 source` | Incorrect S3 key or bucket name | Verify the path + check S3 permissions on the vmimport role |
| `FirstBootFailure` | Boot loader incompatible with EC2 | Retry without `--no-modifications` |
| Stuck in `converting` for a long time | Large disk size | This is normal. Expect approximately 30–60 minutes per 100 GB |

---

## Estimated Duration

| Disk Size | S3 Upload (100 Mbps) | Import Processing | Total |
|-----------|----------------------|-------------------|-------|
| 50 GB | ~70 min | 30–60 min | ~2–2.5 hours |
| 100 GB | ~140 min | 60–90 min | ~4–5 hours |
| 500 GB | ~700 min | 3–5 hours | ~15–17 hours |

> ⚠️ These are the durations for VM Import/Export, which is a fundamentally different approach from the Shift Toolkit's FlexClone conversion (seconds to minutes). VM Import requires a full data copy.

---

*This procedure serves as a backup plan for cases where the Shift Toolkit Early Preview is determined to follow Scenario B (OS disk requires separate AMI creation).*
