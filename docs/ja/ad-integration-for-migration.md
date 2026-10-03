# VMware 移行における Active Directory 連携ガイド

**目的**: VMware ESXi から EC2 + Amazon FSx for NetApp ONTAP へ移行する際、SMB ファイル共有のアクセス権限を維持するための AD 連携設計を解説する。

> 関連テンプレート: [`templates/demo-ad-environment.yaml`](../../templates/demo-ad-environment.yaml)
> 関連スクリプト: [`scripts/demo-ad-join-svm.sh`](../../scripts/demo-ad-join-svm.sh)

---

## 移行元 AD の再利用パターン

VMware 環境で SMB ファイル共有を運用している場合、移行先の FSx for ONTAP でも同一の AD ドメインを利用するのが最も自然な選択肢である。以下に 3 つのパターンを示す。

### Pattern A: AWS Managed Microsoft AD（新規 AD）

| 項目 | 内容 |
|------|------|
| 概要 | AWS 上に新規の Managed AD を構築し、オンプレ AD と信頼関係を設定 |
| 適合ケース | 段階的移行でオンプレ AD への依存を切りたい場合 |
| メリット | AWS 完結、マネージド運用、Multi-AZ 冗長 |
| デメリット | 信頼関係の設定が必要、SID 履歴の移行が複雑 |
| AD 参加方式 | FSx コンソール / API で直接指定 |

### Pattern B: AWS Managed Microsoft AD + 既存 AD の Trust

| 項目 | 内容 |
|------|------|
| 概要 | Managed AD を構築し、既存オンプレ AD とフォレスト信頼を設定 |
| 適合ケース | 既存 AD を残しつつ AWS 側に独立したドメインを持ちたい場合 |
| メリット | 双方のドメインが独立、段階的移行が容易 |
| デメリット | 2 ドメイン運用のオーバーヘッド、名前解決の複雑化 |
| AD 参加方式 | FSx コンソール / API で Managed AD を指定 |

### Pattern C: 既存オンプレ AD をそのまま利用（推奨）

| 項目 | 内容 |
|------|------|
| 概要 | オンプレの既存 AD ドメインに FSx for ONTAP SVM を直接参加させる |
| 適合ケース | VMware 移行で既存の ACL / SID / グループ構造を完全に維持したい場合 |
| メリット | 追加の AD 不要、SID がそのまま有効、ACL の再設定不要 |
| デメリット | オンプレ AD への安定したネットワーク接続が必須 |
| AD 参加方式 | `SelfManagedActiveDirectoryConfiguration` で指定 |

> **VMware 移行では Pattern C を推奨する。** 移行元の NTFS ACL、SID、グループメンバーシップがそのまま移行先で機能するため、ユーザーへの影響が最小限になる。

### 選び方フローチャート

```text
既存 AD を移行後も継続利用する？
├── Yes → オンプレ AD への安定接続を確保できる？
│         ├── Yes → Pattern C（推奨）
│         └── No  → Direct Connect / VPN を構築してから Pattern C
└── No  → AWS に独立ドメインを作る？
          ├── Yes → Pattern A
          └── 既存 AD と信頼関係で共存 → Pattern B
```

---

## AD Connector vs Direct Connect / VPN の選択ガイド

FSx for ONTAP SVM をオンプレ AD に参加させるには、VPC からオンプレ AD ドメインコントローラーへの**ネットワーク到達性**と **DNS 名前解決**が必要である。以下の 2 つのアプローチがある。

### アプローチ 1: Direct Connect / Site-to-Site VPN（ネットワーク直結）

```text
┌─────────────────┐          ┌─────────────────┐
│  AWS VPC        │  DX/VPN  │  On-Premises     │
│                 │◄────────►│                 │
│ FSx for ONTAP   │          │ AD Domain        │
│ Route 53 Resolver│         │ Controller       │
│ EC2 Instances    │          │ DNS Server       │
└─────────────────┘          └─────────────────┘
```

| 項目 | 内容 |
|------|------|
| 構成 | VPN or Direct Connect でオンプレ DC へ L3 到達性を確保 |
| DNS 解決 | Route 53 Outbound Resolver で AD ドメインをオンプレ DNS に転送 |
| 用途 | FSx for ONTAP SVM の AD 参加、SMB クライアント認証 |
| メリット | シンプル、追加サービス不要、レイテンシが低い（DX の場合） |
| デメリット | VPN / DX の構築・運用が必要 |
| 推奨ケース | 既に DX / VPN が存在する環境、本番移行 |

### アプローチ 2: AD Connector（Directory Service 経由）

```text
┌─────────────────┐          ┌─────────────────┐
│  AWS VPC        │  DX/VPN  │  On-Premises     │
│                 │◄────────►│                 │
│ AD Connector ───┼──────────┼►AD Domain       │
│ (proxy)         │          │  Controller     │
│ FSx for ONTAP   │          │                 │
└─────────────────┘          └─────────────────┘
```

| 項目 | 内容 |
|------|------|
| 構成 | AD Connector がオンプレ AD へのプロキシとして動作 |
| DNS 解決 | AD Connector 自体がフォワーダーとして機能 |
| 用途 | WorkSpaces、SSO、EC2 ドメイン参加で AD Connector が必要な場合 |
| メリット | 他の AWS サービス（WorkSpaces 等）との統合が容易 |
| デメリット | AD Connector 自体が追加コスト、DX/VPN は別途必要 |
| 推奨ケース | WorkSpaces や AWS SSO を同時に使う環境 |

### 選択基準まとめ

| 判断基準 | Direct Connect / VPN のみ | AD Connector 追加 |
|---------|--------------------------|-------------------|
| FSx for ONTAP AD 参加 | ✅ 十分 | ✅ 可能（ただし FSx 自体は直接 DC と通信） |
| WorkSpaces 利用 | ❌ 別途 AD 連携が必要 | ✅ AD Connector で統合 |
| AWS SSO (IAM Identity Center) | ❌ 別途設定 | ✅ AD Connector で連携可能 |
| コスト | DX/VPN のみ | DX/VPN + AD Connector 月額 |
| 構成の単純さ | ⭕ シンプル | △ コンポーネント追加 |

> **FSx for ONTAP の AD 参加だけが目的なら、DX/VPN + Route 53 Resolver で十分。** AD Connector は WorkSpaces や IAM Identity Center との統合が必要な場合に追加する。

### 必須ポート一覧

FSx for ONTAP SVM がオンプレ AD ドメインコントローラーと通信するために必要なポート:

| プロトコル | ポート | 用途 |
|-----------|--------|------|
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

## 移行時の SMB 共有 SID 保持に関する注意事項

SID の定義、移行パスごとの保持状況、保持のための必須条件、Shift Toolkit での保持フロー、注意事項と落とし穴、検証手順の順にまとめます。

### SID の定義

Security Identifier (SID) は Windows / AD 環境でユーザー・グループ・コンピュータを一意に識別する値である。NTFS ACL は SID ベースでアクセス権を記録しているため、移行後も同じ SID が解決可能であることが、アクセス権維持の前提条件になる。

### 移行パスごとの SID 保持状況

| 移行方式 | SID 保持 | 条件 |
|---------|---------|------|
| NetApp Shift Toolkit | ✅ | 同一 AD ドメインに参加し、同一 OU 構造を維持 |
| AWS Transform (VM Import 相当) | ✅ | VMDK→AMI 変換後、EC2 を同一ドメインに参加 |
| VM Import/Export | ✅ | 同上 |
| 手動再構築 | ⚠️ | ACL を手動で再設定する必要あり |

### SID 保持のための必須条件

1. **同一 AD ドメインへの参加**: 移行先の FSx for ONTAP SVM が、移行元と同じ AD ドメインに参加していること
2. **OU 構造の維持**: `SelfManagedAdOu` パラメータで移行元と同じ OU パスを指定すること
3. **SID フィルタリングの無効化**: フォレスト信頼を使う場合（Pattern B）、SID フィルタリングが有効だと SID 履歴が無視される
4. **NTFS ACL のコピー**: データ移行時に ACL を保持する方式を選択すること

### Shift Toolkit での SID 保持フロー

```text
[VMware VMDK]
    │  NTFS ACL (SID ベース) が含まれたまま変換
    ▼
[FSx for ONTAP Volume]
    │  同一 AD ドメインに SVM が参加済み
    ▼
[SID → ユーザー/グループ解決]
    │  AD が同一なので SID がそのまま有効
    ▼
[アクセス権維持完了]
```

### 注意事項と落とし穴

SID 保持で踏みやすい落とし穴を 4 つ挙げます。コンピュータアカウントの重複、sIDHistory の扱い、ローカル SID、継承 ACL と明示 ACL です。

#### 1. コンピュータアカウントの重複

移行元の VMware 上の Windows Server と、移行先の FSx for ONTAP SVM が同じ NetBIOS 名で AD に参加しようとすると、コンピュータアカウントが競合する。

**対策**: 移行前に移行元のコンピュータアカウントを無効化するか、FSx for ONTAP SVM には別の NetBIOS 名を使用する。

#### 2. SID 履歴 (sIDHistory) の扱い

ドメイン間移行（Pattern B）では、`sIDHistory` 属性にソースドメインの SID を格納することで旧 ACL を解決可能にする。ただし:

- フォレスト信頼で SID フィルタリングが有効な場合は無効
- `sIDHistory` の移行には AD Migration Tool (ADMT) 等が必要
- FSx for ONTAP 自体は `sIDHistory` を直接操作しない（AD 側の設定）

#### 3. ローカル SID（ドメイン外アカウント）

ワークグループモードのファイルサーバーで付与されたローカル SID は、AD ドメインでは解決できない。移行前にドメインアカウントベースの ACL へ変換が必要。

#### 4. 継承された ACL と明示的 ACL

NTFS ACL には親フォルダから継承されたエントリと、明示的に設定されたエントリがある。Shift Toolkit / robocopy でのコピー時に `/SEC` や `/COPYALL` オプションの挙動を確認すること。

### 検証手順

移行後の SID 保持を確認するチェックリスト:

```bash
# 1. SVM が正しい AD ドメインに参加しているか確認
aws fsx describe-storage-virtual-machines \
  --storage-virtual-machine-ids svm-xxxx \
  --query 'StorageVirtualMachines[0].ActiveDirectoryConfiguration'

# 2. SMB 共有にアクセスし、ACL を確認 (Windows クライアント)
# icacls \\svm-smb.corp.example.com\share1

# 3. SID 解決の確認 (Linux / wbinfo)
# wbinfo -s S-1-5-21-xxxxxxxxxx-xxxxxxxxxx-xxxxxxxxxx-1234

# 4. 特定ユーザーでのアクセステスト
# smbclient //svm-smb.corp.example.com/share1 -U user@corp.example.com
```

---

## デプロイ手順

CloudFormation スタックのデプロイ（1）、必要な場合のみ AD Connector のデプロイ（2）、SVM の AD 参加（3）の順に実行します。

### 1. CloudFormation スタックのデプロイ

```bash
# パラメータファイルを編集
cp params/demo-ad-environment.example.json params/demo-ad-environment.json
# → 実環境の値に書き換え

# スタックデプロイ
aws cloudformation deploy \
  --template-file templates/demo-ad-environment.yaml \
  --stack-name demo-ad-environment \
  --parameter-overrides file://params/demo-ad-environment.json \
  --region ap-northeast-1
```

### 2. AD Connector のデプロイ（必要な場合のみ）

```bash
# AD Connector は CloudFormation 非対応のため CLI で作成
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

### 3. SVM の AD 参加

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

## トラブルシューティング

| 症状 | 原因 | 対策 |
|------|------|------|
| SVM AD 参加が FAILED | DNS で AD ドメインを解決できない | Route 53 Resolver Rule を確認、`nslookup corp.example.com` で検証 |
| SVM AD 参加が FAILED | サービスアカウントに OU 権限がない | AD 上で OU のデリゲーション設定を確認 |
| SVM AD 参加が FAILED | OU パスが存在しない | `dsquery ou -name "FSxONTAP"` で OU の存在を確認 |
| SMB アクセスで Access Denied | SID が解決できない | `wbinfo -s <SID>` で名前解決を確認 |
| 認証が Kerberos ではなく NTLM | DNS 逆引きが未設定 | PTR レコードの追加、または SPN の確認 |
| FlexClone 先で ACL が無効 | クローン先 SVM が別ドメイン | 同一 AD ドメインに参加させる |

---

---

## Windows EC2 ドメイン参加時の落とし穴（SSM Association）

移行した Windows EC2 インスタンスを AD ドメインに参加させる場合、CloudFormation で SSM を使う方法に**既知のデプロイ失敗パターン**がある。

### 失敗するパターン（使用禁止）

```yaml
# ❌ EC2 の SsmAssociations プロパティ + カスタム SSM Document
# エラー: "Document schema version, 2.2, is not supported by association
#          that is created with instance id"
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
      - DocumentName: !Ref AdJoinDocument  # ← ここで失敗
```

**失敗の原因**:

- EC2 の `SsmAssociations` プロパティは内部的に SSM State Manager Association を作成する
- `aws:domainJoin` プラグインは AWS 管理ドキュメント `AWS-JoinDirectoryServiceDomain` 経由でのみ正しく動作する
- カスタム SSM Document で同じアクションを定義しても `schemaVersion` 互換性エラーが発生する
- `schemaVersion: '1.2'` にダウングレードしても構文が異なり動作しない

### 正しいパターン（必須）

```yaml
# ✅ EC2 インスタンスから SsmAssociations プロパティを削除
WindowsInstance:
  Type: AWS::EC2::Instance
  Properties:
    ImageId: !Ref WindowsAmiId
    InstanceType: !Ref InstanceType
    IamInstanceProfile: !Ref Ec2InstanceProfile
    # SsmAssociations は使用しない

# ✅ 別リソースとして SSM Association を作成
# AWS 管理ドキュメント「AWS-JoinDirectoryServiceDomain」を使用
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

### EC2 インスタンスの IAM ロールに必要なポリシー

```yaml
ManagedPolicyArns:
  - arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  - arn:aws:iam::aws:policy/AmazonSSMDirectoryServiceAccess  # domain join に必須
```

> **Security note**: この問題は fsxn-observability-integrations プロジェクトの実機検証で確認済み。新規テンプレート作成時は必ず `AWS::SSM::Association` + `AWS-JoinDirectoryServiceDomain` パターンを使用すること。

---

## 参考リンク

- [FSx for ONTAP: Using a self-managed Microsoft AD](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/self-managed-AD.html)
- [FSx for ONTAP: Best practices for joining SVMs to an AD](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ad-best-practices.html)
- [AD Connector の前提条件](https://docs.aws.amazon.com/directoryservice/latest/admin-guide/prereq_connector.html)
- [Route 53 Resolver Rules](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-rules-managing.html)
- [SSM State Manager Association](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-state-assoc.html)
