# Active Directory Integration Guide for VMware Migration

**Purpose**: Design guidance for AD integration when migrating from VMware ESXi to EC2 + Amazon FSx for NetApp ONTAP, ensuring SMB file share access permissions are preserved.

> Related template: [`templates/demo-ad-environment.yaml`](../../templates/demo-ad-environment.yaml)
> Related script: [`scripts/demo-ad-join-svm.sh`](../../scripts/demo-ad-join-svm.sh)

---

## Reusing the Migration Source AD

When operating SMB file shares in a VMware environment, using the same AD domain at the migration target (FSx for ONTAP) is the most natural choice. Three patterns are available:

### Pattern A: AWS Managed Microsoft AD (New AD)

| Item | Details |
|------|---------|
| Overview | Build a new Managed AD on AWS and configure trust with on-premises AD |
| Fit | Gradual migration with intent to decouple from on-prem AD |
| Pros | AWS-managed, Multi-AZ redundancy, no on-prem dependency long-term |
| Cons | Trust configuration required, SID history migration is complex |
| AD Join Method | Specify directly in FSx console / API |

### Pattern B: AWS Managed Microsoft AD + Existing AD Trust

| Item | Details |
|------|---------|
| Overview | Build Managed AD and configure forest trust with existing on-prem AD |
| Fit | Maintain separate domains while preserving cross-domain access |
| Pros | Independent domains, gradual migration path |
| Cons | Dual-domain operational overhead, DNS complexity |
| AD Join Method | Specify Managed AD via FSx console / API |

### Pattern C: Use Existing On-Premises AD Directly (Recommended)

| Item | Details |
|------|---------|
| Overview | Join FSx for ONTAP SVM directly to the existing on-prem AD domain |
| Fit | VMware migration requiring complete preservation of ACLs / SIDs / groups |
| Pros | No additional AD, SIDs remain valid, no ACL reconfiguration |
| Cons | Stable network connectivity to on-prem AD is mandatory |
| AD Join Method | `SelfManagedActiveDirectoryConfiguration` |

> **Pattern C is recommended for VMware migrations.** Source NTFS ACLs, SIDs, and group memberships work immediately at the target, minimizing user impact.

### Decision Flowchart

```text
Will you continue using the existing AD after migration?
├── Yes → Can you ensure stable connectivity to on-prem AD?
│         ├── Yes → Pattern C (Recommended)
│         └── No  → Establish Direct Connect / VPN, then Pattern C
└── No  → Create an independent domain on AWS?
          ├── Yes → Pattern A
          └── Coexist via trust with existing AD → Pattern B
```

---

## AD Connector vs Direct Connect / VPN Selection Guide

To join an FSx for ONTAP SVM to an on-prem AD, the VPC requires **network reachability** and **DNS name resolution** to the on-prem Domain Controllers. Two approaches exist:

### Approach 1: Direct Connect / Site-to-Site VPN (Direct Network)

```text
┌─────────────────┐          ┌─────────────────┐
│  AWS VPC        │  DX/VPN  │  On-Premises     │
│                 │◄────────►│                 │
│ FSx for ONTAP   │          │ AD Domain        │
│ Route 53 Resolver│         │ Controller       │
│ EC2 Instances    │          │ DNS Server       │
└─────────────────┘          └─────────────────┘
```

| Item | Details |
|------|---------|
| Configuration | VPN or Direct Connect provides L3 reachability to on-prem DCs |
| DNS Resolution | Route 53 Outbound Resolver forwards AD domain queries to on-prem DNS |
| Use Case | FSx for ONTAP SVM AD join, SMB client authentication |
| Pros | Simple, no additional services, low latency (with DX) |
| Cons | Requires VPN / DX setup and operations |
| Recommended For | Environments with existing DX / VPN, production migrations |

### Approach 2: AD Connector (via Directory Service)

```text
┌─────────────────┐          ┌─────────────────┐
│  AWS VPC        │  DX/VPN  │  On-Premises     │
│                 │◄────────►│                 │
│ AD Connector ───┼──────────┼►AD Domain       │
│ (proxy)         │          │  Controller     │
│ FSx for ONTAP   │          │                 │
└─────────────────┘          └─────────────────┘
```

| Item | Details |
|------|---------|
| Configuration | AD Connector acts as a proxy to on-prem AD |
| DNS Resolution | AD Connector itself functions as a DNS forwarder |
| Use Case | When AD Connector is needed for WorkSpaces, SSO, or EC2 domain join |
| Pros | Easy integration with other AWS services (WorkSpaces, etc.) |
| Cons | Additional cost for AD Connector; DX/VPN still required |
| Recommended For | Environments using WorkSpaces or AWS SSO alongside migration |

### Selection Criteria Summary

| Criterion | Direct Connect / VPN Only | Add AD Connector |
|-----------|--------------------------|------------------|
| FSx for ONTAP AD join | ✅ Sufficient | ✅ Possible (FSx communicates directly with DCs) |
| WorkSpaces usage | ❌ Requires separate AD integration | ✅ Integrated via AD Connector |
| AWS SSO (IAM Identity Center) | ❌ Separate configuration | ✅ Integrated via AD Connector |
| Cost | DX/VPN only | DX/VPN + AD Connector monthly fee |
| Simplicity | ⭕ Simple | △ Additional component |

> **If your sole objective is FSx for ONTAP AD join, DX/VPN + Route 53 Resolver is sufficient.** Add AD Connector only when WorkSpaces or IAM Identity Center integration is also required.

### Required Ports

Ports required for FSx for ONTAP SVM communication with on-prem AD Domain Controllers:

| Protocol | Port | Purpose |
|----------|------|---------|
| TCP/UDP | 53 | DNS |
| TCP/UDP | 88 | Kerberos |
| TCP/UDP | 389 | LDAP |
| TCP | 636 | LDAPS |
| TCP | 445 | SMB/CIFS |
| TCP | 135 | RPC Endpoint Mapper |
| TCP | 49152-65535 | RPC Dynamic Ports |
| TCP | 3268-3269 | Global Catalog |
| UDP | 123 | NTP |

---

## SMB Share SID Preservation During Migration

This covers, in order: what a SID is, how it is preserved by migration method, the mandatory conditions for preservation, the preservation flow with Shift Toolkit, caveats and pitfalls, and the verification procedure.

### What is a SID?

A Security Identifier (SID) uniquely identifies users, groups, and computers in Windows / AD environments. NTFS ACLs record access permissions using SIDs, so the ability to resolve the same SIDs after migration is a prerequisite for access permission preservation.

### SID Preservation by Migration Method

| Migration Method | SID Preserved | Conditions |
|-----------------|---------------|------------|
| NetApp Shift Toolkit | ✅ | Same AD domain joined, same OU structure maintained |
| AWS Transform (VM Import equivalent) | ✅ | After VMDK→AMI conversion, join EC2 to same domain |
| VM Import/Export | ✅ | Same as above |
| Manual rebuild | ⚠️ | ACLs must be manually reconfigured |

### Mandatory Conditions for SID Preservation

1. **Same AD domain membership**: The target FSx for ONTAP SVM must join the same AD domain as the migration source
2. **OU structure maintenance**: Specify the same OU path using the `SelfManagedAdOu` parameter
3. **SID filtering disabled**: When using forest trusts (Pattern B), SID filtering causes SID history to be ignored
4. **NTFS ACL copy**: Choose a data migration method that preserves ACLs

### SID Preservation Flow with Shift Toolkit

```text
[VMware VMDK]
    │  Converted with NTFS ACL (SID-based) intact
    ▼
[FSx for ONTAP Volume]
    │  SVM already joined to the same AD domain
    ▼
[SID → User/Group Resolution]
    │  Same AD means SIDs resolve directly
    ▼
[Access Permissions Preserved]
```

### Caveats and Pitfalls

Four pitfalls come up when preserving SIDs: computer account conflicts, sIDHistory handling, local SIDs, and inherited versus explicit ACLs.

#### 1. Computer Account Conflicts

If the source VMware Windows Server and the target FSx for ONTAP SVM attempt to join AD with the same NetBIOS name, computer accounts will conflict.

**Mitigation**: Disable the source computer account before migration, or use a different NetBIOS name for the FSx for ONTAP SVM.

#### 2. SID History (sIDHistory) Handling

For cross-domain migration (Pattern B), storing the source domain SID in the `sIDHistory` attribute enables resolution of legacy ACLs. However:

- Ineffective if SID filtering is enabled on the forest trust
- Migrating `sIDHistory` requires AD Migration Tool (ADMT) or similar
- FSx for ONTAP does not directly manipulate `sIDHistory` (this is an AD-side configuration)

#### 3. Local SIDs (Non-Domain Accounts)

Local SIDs assigned by workgroup-mode file servers cannot be resolved in an AD domain. Convert ACLs to domain-account-based entries before migration.

#### 4. Inherited vs Explicit ACLs

NTFS ACLs contain entries inherited from parent folders and explicitly set entries. Verify the behavior of `/SEC` or `/COPYALL` options when copying with Shift Toolkit / robocopy.

### Verification Procedure

Post-migration SID preservation checklist:

```bash
# 1. Verify SVM is joined to the correct AD domain
aws fsx describe-storage-virtual-machines \
  --storage-virtual-machine-ids svm-xxxx \
  --query 'StorageVirtualMachines[0].ActiveDirectoryConfiguration'

# 2. Check ACLs on SMB share (Windows client)
# icacls \\svm-smb.corp.example.com\share1

# 3. Verify SID resolution (Linux / wbinfo)
# wbinfo -s S-1-5-21-xxxxxxxxxx-xxxxxxxxxx-xxxxxxxxxx-1234

# 4. Test access with a specific user
# smbclient //svm-smb.corp.example.com/share1 -U user@corp.example.com
```

---

## Deployment Steps

Run in order: deploy the CloudFormation stack (1), deploy AD Connector only if required (2), and join the SVM to AD (3).

### 1. Deploy CloudFormation Stack

```bash
# Edit parameter file
cp params/demo-ad-environment.example.json params/demo-ad-environment.json
# → Replace with actual environment values

# Deploy stack
aws cloudformation deploy \
  --template-file templates/demo-ad-environment.yaml \
  --stack-name demo-ad-environment \
  --parameter-overrides file://params/demo-ad-environment.json \
  --region ap-northeast-1
```

### 2. Deploy AD Connector (If Required)

```bash
# AD Connector is not supported as a CloudFormation resource; use CLI
aws ds connect-directory \
  --name corp.example.com \
  --short-name CORP \
  --size Small \
  --connect-settings \
    SubnetIds=subnet-xxxx,subnet-yyyy \
    VpcId=vpc-xxxx \
    CustomerDnsIps=198.51.100.10,198.51.100.11 \
    CustomerUserName=svc-ad-connector \
  --password '<service-account-password>' \
  --region ap-northeast-1
```

### 3. Join SVM to AD

```bash
./scripts/demo-ad-join-svm.sh \
  --filesystem-id fs-0123456789abcdef0 \
  --svm-name svm-smb \
  --domain corp.example.com \
  --ou "OU=FSxONTAP,OU=Servers,DC=corp,DC=example,DC=com" \
  --dns-ips 198.51.100.10,198.51.100.11 \
  --admin-user svc-fsx-adjoin
```

---

## Troubleshooting

| Symptom | Cause | Remedy |
|---------|-------|--------|
| SVM AD join FAILED | Cannot resolve AD domain via DNS | Verify Route 53 Resolver Rule; test with `nslookup corp.example.com` |
| SVM AD join FAILED | Service account lacks OU permissions | Verify OU delegation settings in AD |
| SVM AD join FAILED | OU path does not exist | Verify with `dsquery ou -name "FSxONTAP"` |
| Access Denied on SMB | SID cannot be resolved | Verify with `wbinfo -s <SID>` |
| Auth falls back to NTLM | DNS reverse lookup not configured | Add PTR records or verify SPNs |
| ACLs invalid on FlexClone target | Clone target SVM in different domain | Join to the same AD domain |

---

---

## Windows EC2 Domain Join Pitfall (SSM Association)

When joining migrated Windows EC2 instances to an AD domain, there is a **known deployment failure pattern** when using SSM via CloudFormation.

### Pattern That Fails (Do Not Use)

```yaml
# ❌ EC2 SsmAssociations property + custom SSM Document
# Error: "Document schema version, 2.2, is not supported by association
#         that is created with instance id"
AdJoinDocument:
  Type: AWS::SSM::Document
  Properties:
    DocumentType: Command
    Content:
      schemaVersion: '2.2'
      mainSteps:
        - action: aws:domainJoin
          ...

WindowsInstance:
  Type: AWS::EC2::Instance
  Properties:
    SsmAssociations:
      - DocumentName: !Ref AdJoinDocument  # ← Fails here
```

**Why it fails**:

- EC2's `SsmAssociations` property internally creates an SSM State Manager Association
- The `aws:domainJoin` plugin only works correctly via the AWS-managed document `AWS-JoinDirectoryServiceDomain`
- Defining the same action in a custom SSM Document triggers a `schemaVersion` compatibility error
- Downgrading to `schemaVersion: '1.2'` uses different syntax and does not work either

### Correct Pattern (Required)

```yaml
# ✅ Remove SsmAssociations property from EC2 instance
WindowsInstance:
  Type: AWS::EC2::Instance
  Properties:
    ImageId: !Ref WindowsAmiId
    InstanceType: !Ref InstanceType
    IamInstanceProfile: !Ref Ec2InstanceProfile
    # Do NOT use SsmAssociations

# ✅ Create SSM Association as a separate resource
# Use AWS-managed document "AWS-JoinDirectoryServiceDomain"
DomainJoinAssociation:
  Type: AWS::SSM::Association
  Properties:
    Name: AWS-JoinDirectoryServiceDomain
    Targets:
      - Key: InstanceIds
        Values:
          - !Ref WindowsInstance
    Parameters:
      directoryId:
        - !Ref DirectoryId
      directoryName:
        - !Ref AdDomainName
      dnsIpAddresses:
        - !Select [0, !GetAtt ManagedAD.DnsIpAddresses]
        - !Select [1, !GetAtt ManagedAD.DnsIpAddresses]
```

### Required IAM Policies on EC2 Instance Role

```yaml
ManagedPolicyArns:
  - arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  - arn:aws:iam::aws:policy/AmazonSSMDirectoryServiceAccess  # Required for domain join
```

> **Security note**: This issue was confirmed via hands-on testing in the fsxn-observability-integrations project. Always use the `AWS::SSM::Association` + `AWS-JoinDirectoryServiceDomain` pattern when creating new templates.

---

## References

- [FSx for ONTAP: Using a self-managed Microsoft AD](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/self-managed-AD.html)
- [FSx for ONTAP: Best practices for joining SVMs to an AD](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ad-best-practices.html)
- [AD Connector Prerequisites](https://docs.aws.amazon.com/directoryservice/latest/admin-guide/prereq_connector.html)
- [Route 53 Resolver Rules](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-rules-managing.html)
- [SSM State Manager Association](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-state-assoc.html)
