# VMware to EC2 + FSx for ONTAP Migration Path Verification

[![CI](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/ci.yml/badge.svg)](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/ci.yml)
[![Gitleaks](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/gitleaks.yml)

🌐 **Language / 言語**: [日本語](README.md) | English (this page)

> Hands-on verification of VMware ESXi → Amazon EC2 + Amazon FSx for NetApp ONTAP migration across multiple paths.
> Confirms whether existing ONTAP operational models carry over to AWS with cloud-native scalability and cost optimization.

## Get Started

| Goal | Guide | Time |
|:-----|:------|:-----|
| Compare migration approaches | [Migration Method Comparison](docs/en/migration-method-comparison.md) | 10 min |
| Migrate with Shift Toolkit | [Shift Toolkit Procedure](docs/en/shift-toolkit-ec2-procedure.md) | 30 min |
| Migrate with AWS Transform | [AWS Transform Procedure](docs/en/aws-transform-migration-procedure.md) | 30 min |
| Migrate with VM Import/Export | [VM Import Procedure](docs/en/vm-import-procedure.md) | 20 min |
| Set up PoC environment | [Quick Start](docs/en/quickstart.md) | 15 min |
| Configure iSCSI LUNs | [iSCSI Setup](docs/en/fsxn-iscsi-setup.md) | 15 min |

> **The parts that a migration runbook does not carry** — where the rollback window closes, the capacity peak at Finalize, ACL preservation, and how LUN placement decides recovery granularity — are in the sibling repository [FSx for ONTAP Adoption Playbook — 03 Migrate](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/playbooks/03-migrate/README.md). Referenced rather than copied here.

<details><summary>📂 All Documents</summary>

| Document | Description |
|:---------|:------------|
| [Research Summary](docs/en/research-summary.md) | Technical research & tool comparison |
| [AD Integration Guide](docs/en/ad-integration-for-migration.md) | Active Directory integration patterns |
| [DR SnapMirror Runbook](docs/en/dr-snapmirror-runbook.md) | DR design using SnapMirror |
| [PoC Plan Template](docs/en/poc-plan-template.md) | Success criteria & verification plan |
| [NetApp Q&A](docs/en/netapp-questions.md) | Questions for NetApp |

</details>

## Architecture

```text
[On-Premises]                          [AWS]
VMware ESXi                            Amazon EC2 (Nitro)
  └── VM (VMDK on ONTAP NFS)             ├── Boot: EBS gp3
                                         └── Data: FSx for ONTAP (iSCSI LUN)

Path A ─ Shift Toolkit: FlexClone conversion → SnapMirror → EBS AMI → EC2 launch
Path B ─ AWS Transform: Discovery → Wave Plan → MGN replication → Cutover
```

| Condition | Suited Tool |
|:----------|:------------|
| No ONTAP / EBS-only sufficient | AWS MGN |
| ONTAP in use + small/mid-scale | Shift Toolkit (Early Preview) |
| ONTAP in use + 100+ VMs + near-zero downtime | Cirrus Migrate Cloud |
| AWS-native end-to-end / mixed sources | AWS Transform (Public Preview) |

<details><summary>⚠️ Constraints & Caveats</summary>

| Item | Detail |
|:-----|:-------|
| Shift Toolkit | Early Preview — requires enablement by NetApp |
| AWS Transform | FSx for ONTAP destination is Public Preview — region/UI may change |
| Specifications | Do not treat either tool as GA |
| Region | Verified in Tokyo (ap-northeast-1) |
| Connectivity | VPN or Direct Connect required (on-prem ↔ AWS) |

Details: [PoC Plan Template](docs/en/poc-plan-template.md)

</details>

<details><summary>📚 References</summary>

**NetApp**

- [Shift Toolkit (MySupport — login required)](https://mysupport.netapp.com/site/tools/tool-eula/netapp-shift-toolkit)
- [Migrate VMware to EC2 & iSCSI-based FSx for ONTAP (Blog)](https://www.netapp.com/blog/aws-fsxn-blg-migrate-vmware-to-amazon-ec2-iscsi-based-fsx-for-ontap/)
- [Simplify VM migration with Shift Toolkit (Blog)](https://www.netapp.com/blog/simplify-vm-migration-shift-toolkit/)

**AWS**

- [AWS Transform: VMware to FSx for ONTAP (What's New)](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/)
- [Accelerating VMware migration: AWS Transform (Blog)](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/)
- [Seamless VMware Migration (Storage Blog)](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/)
- [Amazon FSx for NetApp ONTAP](https://aws.amazon.com/fsx/netapp-ontap/)
- [AWS Transform Pricing](https://aws.amazon.com/transform/pricing/)

</details>

<details><summary>🔧 For Developers</summary>

```bash
git clone https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP.git
cd VMware-Migration-EC2-ONTAP
git config core.hooksPath .githooks
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/verify-setup.sh
```

- Python 3.12+ / Bash / CloudFormation YAML
- Lint: `cfn-lint templates/*.yaml`
- Security: `gitleaks detect --config .gitleaks.toml --no-git --source .`

Full setup details: [Quick Start](docs/en/quickstart.md)

</details>

## License

MIT

---

🌐 **Language / 言語**: [日本語](README.md) | English (this page)
