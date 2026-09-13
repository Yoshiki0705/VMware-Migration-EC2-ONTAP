# クイックスタート

🌐 [English](../en/quickstart.md) | 日本語 (このページ)

> PoC 環境の構築手順（VPC + FSx for ONTAP + EC2）

## 前提条件

### オンプレミス側

- VMware vCenter 7.0.3 以降（ESXi ホスト + NFS データストア）
- ONTAP 9.14.1 以降
- NetApp Shift Toolkit（Windows Server 上にインストール — Shift Toolkit 検証の場合）
- NetApp Support アカウント（Early Preview 有効化用）

### AWS 側

- AWS アカウント + 適切な IAM 権限
- AWS CLI v2 設定済み（`aws sts get-caller-identity` が成功すること）
- AWS Organizations + IAM Identity Center（AWS Transform の前提）
- VPN or Direct Connect（オンプレ ↔ AWS 間接続）
- 東京リージョン (ap-northeast-1) 推奨

## セットアップ

```bash
# リポジトリクローン
git clone https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP.git
cd VMware-Migration-EC2-ONTAP

# Git hooks 設定
git config core.hooksPath .githooks

# Python 仮想環境セットアップ
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 環境検証（AWS CLI 認証、リージョン確認等）
bash scripts/verify-setup.sh
```

## PoC 環境デプロイ

CloudFormation テンプレートで VPC + FSx for ONTAP + EC2 をデプロイします。

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

### パラメータ

| パラメータ | デフォルト | 説明 |
|:----------|:----------|:-----|
| `VpcCidr` | `10.0.0.0/16` | VPC CIDR ブロック |
| `FsxnThroughput` | `512` | FSx for ONTAP スループットキャパシティ (MBps) |
| `FsxnStorageCapacity` | `1024` | FSx for ONTAP ストレージ容量 (GiB) |

### AD 環境付きデプロイ

Active Directory 統合が必要な場合は、AD 環境テンプレートを使用します。

```bash
# パラメータファイルを作成
cp params/demo-ad-environment.example.json params/demo-ad-environment.json
# params/demo-ad-environment.json を編集

aws cloudformation deploy \
  --template-file templates/demo-ad-environment.yaml \
  --stack-name vmware-migration-ad \
  --parameter-overrides file://params/demo-ad-environment.json \
  --capabilities CAPABILITY_IAM
```

AD 統合の詳細: [AD 統合ガイド](ad-integration-for-migration.md)

## スタック削除

```bash
aws cloudformation delete-stack --stack-name vmware-migration-poc
aws cloudformation wait stack-delete-complete --stack-name vmware-migration-poc
```

### 削除が DELETE_FAILED で止まる条件

**このテンプレートが作るのは FSx for ONTAP のファイルシステムだけで、SVM とボリュームは含みません。**
AWS Transform や移行ツールがファイルシステム上に SVM / ボリュームを作った後は、
CloudFormation がそれらを所有していないため削除が `DELETE_FAILED` で止まります。
ONTAP のファイルシステム削除は、**すべてのボリュームと SVM を先に削除することが前提**です
（[Deleting file systems](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/delete-file-system.html)）。

```bash
# 残っているものを確認する
aws fsx describe-volumes --filters Name=file-system-id,Values=<fs-id> \
  --query 'Volumes[].{Id:VolumeId,Name:Name}' --output table
aws fsx describe-storage-virtual-machines \
  --filters Name=file-system-id,Values=<fs-id> \
  --query 'StorageVirtualMachines[].{Id:StorageVirtualMachineId,Name:Name}' --output table

# ボリューム → SVM の順に削除してから、スタック削除を 1 回再試行する
aws cloudformation delete-stack --stack-name vmware-migration-poc
```

**`DELETE_FAILED` は 1 度の再試行で消えることが多いので、再試行を手順に含めてください。**

### ボリューム削除が残す最終バックアップ

**`aws fsx delete-volume` は既定で最終バックアップを取ります**
（[Deleting volumes](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/deleting-volumes.html)）。
スキップするには削除時に指定します。

```bash
aws fsx delete-volume --volume-id <fsvol-id> \
  --ontap-configuration SkipFinalBackup=true
```

**`SkipFinalBackup` をテンプレート側に書くことはできません。** `DeleteVolume` API のパラメータで、
`AWS::FSx::Volume` の `OntapConfiguration`
（[プロパティ一覧](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-fsx-volume-ontapconfiguration.html)）
には存在しません。**CloudFormation でボリュームを削除すると最終バックアップが 1 つ残り、課金が続きます。**
削除後に `aws fsx describe-backups` で確認してください。

## 次のステップ

- [移行方式比較表](migration-method-comparison.md) — どのツールを使うか決める
- [Shift Toolkit 手順書](shift-toolkit-ec2-procedure.md) — Shift Toolkit で移行する
- [AWS Transform 手順書](aws-transform-migration-procedure.md) — AWS Transform で移行する
- [iSCSI セットアップ](fsxn-iscsi-setup.md) — FSx for ONTAP iSCSI LUN を設定する
