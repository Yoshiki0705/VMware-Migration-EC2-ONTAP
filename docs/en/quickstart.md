# Quick Start

🌐 English (this page) | [日本語](../ja/quickstart.md)

> PoC environment setup (VPC + FSx for ONTAP + EC2)

## Prerequisites

### On-Premises

- VMware vCenter 7.0.3+ (ESXi hosts + NFS datastore)
- ONTAP 9.14.1+
- NetApp Shift Toolkit (installed on Windows Server — for Shift Toolkit verification)
- NetApp Support account (for Early Preview enablement)

### AWS

- AWS account with appropriate IAM permissions
- AWS CLI v2 configured (`aws sts get-caller-identity` must succeed)
- AWS Organizations + IAM Identity Center (required for AWS Transform)
- VPN or Direct Connect (on-prem ↔ AWS connectivity)
- Tokyo Region (ap-northeast-1) recommended

## Setup

```bash
# Clone repository
git clone https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP.git
cd VMware-Migration-EC2-ONTAP

# Set up git hooks
git config core.hooksPath .githooks

# Python virtual environment setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Verify environment (AWS CLI auth, region, etc.)
bash scripts/verify-setup.sh
```

## Deploy PoC Environment

Deploy VPC + FSx for ONTAP + EC2 using the CloudFormation template.

```bash
aws cloudformation deploy \
  --template-file templates/poc-environment.yaml \
  --stack-name vmware-migration-poc \
  --parameter-overrides \
    VpcCidr=10.0.0.0/16 \
    FsxnThroughput=512 \
    FsxnStorageCapacity=1024 \
  --capabilities CAPABILITY_IAM
```

### Parameters

| Parameter | Default | Description |
|:----------|:--------|:------------|
| `VpcCidr` | `10.0.0.0/16` | VPC CIDR block |
| `FsxnThroughput` | `512` | FSx for ONTAP throughput capacity (MBps) |
| `FsxnStorageCapacity` | `1024` | FSx for ONTAP storage capacity (GiB) |

### Deploy with AD Environment

If Active Directory integration is required, use the AD environment template.

```bash
# Create parameter file
cp params/demo-ad-environment.example.json params/demo-ad-environment.json
# Edit params/demo-ad-environment.json

aws cloudformation deploy \
  --template-file templates/demo-ad-environment.yaml \
  --stack-name vmware-migration-ad \
  --parameter-overrides file://params/demo-ad-environment.json \
  --capabilities CAPABILITY_IAM
```

AD integration details: [AD Integration Guide](ad-integration-for-migration.md)

## Delete Stack

```bash
aws cloudformation delete-stack --stack-name vmware-migration-poc
aws cloudformation wait stack-delete-complete --stack-name vmware-migration-poc
```

### When deletion stops at DELETE_FAILED

**This template creates only the FSx for ONTAP file system, not the SVMs or volumes.** Once AWS
Transform or a migration tool has created SVMs and volumes on that file system, CloudFormation does
not own them and deletion stops at `DELETE_FAILED`. Deleting an ONTAP file system **requires
deleting every volume and SVM first**
([Deleting file systems](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/delete-file-system.html)).

```bash
# See what is left
aws fsx describe-volumes --filters Name=file-system-id,Values=<fs-id> \
  --query 'Volumes[].{Id:VolumeId,Name:Name}' --output table
aws fsx describe-storage-virtual-machines \
  --filters Name=file-system-id,Values=<fs-id> \
  --query 'StorageVirtualMachines[].{Id:StorageVirtualMachineId,Name:Name}' --output table

# Delete volumes, then SVMs, then retry the stack deletion once
aws cloudformation delete-stack --stack-name vmware-migration-poc
```

**One retry usually clears `DELETE_FAILED`, so make the retry part of the procedure.**

### The final backup a volume deletion leaves behind

**`aws fsx delete-volume` takes a final backup by default**
([Deleting volumes](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/deleting-volumes.html)).
Skipping it is specified at deletion time.

```bash
aws fsx delete-volume --volume-id <fsvol-id> \
  --ontap-configuration SkipFinalBackup=true
```

**`SkipFinalBackup` cannot be set in the template.** It is a `DeleteVolume` API parameter and does
not appear in the `OntapConfiguration` of `AWS::FSx::Volume`
([property list](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-fsx-volume-ontapconfiguration.html)).
**Deleting a volume through CloudFormation therefore leaves one final backup, and it keeps
billing.** Check with `aws fsx describe-backups` after deletion.

## Next Steps

- [Migration Method Comparison](migration-method-comparison.md) — Choose which tool to use
- [Shift Toolkit Procedure](shift-toolkit-ec2-procedure.md) — Migrate with Shift Toolkit
- [AWS Transform Procedure](aws-transform-migration-procedure.md) — Migrate with AWS Transform
- [iSCSI Setup](fsxn-iscsi-setup.md) — Configure FSx for ONTAP iSCSI LUNs
