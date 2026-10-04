# シナリオ B 手順書: VM Import/Export による OS ディスクの AMI 化

**目的**: Shift Toolkit Early Preview が OS ディスクをカバーしない場合（シナリオ B）のバックアッププラン。
VMware の VMDK を S3 経由で AWS に転送し、AMI として登録する手順。

> 参考: [AWS VM Import/Export ドキュメント](https://docs.aws.amazon.com/vm-import/latest/userguide/vmimport-image-import.html)

---

## 前提条件

- AWS CLI v2 インストール済み
- S3 バケット作成済み（VMDK アップロード用）
- IAM ロール `vmimport` が作成済み（[公式手順](https://docs.aws.amazon.com/vm-import/latest/userguide/required-permissions.html)参照）
- ソース VM が停止状態
- サポートされるディスクフォーマット: VMDK, VHD, VHDX, RAW

---

## 手順

Step 1 から Step 6 までを順に実行します。VMDK をエクスポートし、S3 へアップロードし、`import-image` を実行し、進捗を確認し、できた AMI から EC2 インスタンスを起動し、起動後を確認します。

### Step 1: VMware からの VMDK エクスポート

```bash
# vCenter / ESXi から VMDK をエクスポート
# 方法 A: vSphere Client で OVF エクスポート → VMDK を抽出
# 方法 B: vmkfstools でコピー（ESXi SSH）
vmkfstools -i /vmfs/volumes/datastore1/vm-name/vm-name.vmdk \
  /vmfs/volumes/datastore1/export/vm-name-flat.vmdk -d thin
```

**注意**: エクスポートする VMDK は「flat」形式（monolithic）であること。スパースディスクは VM Import 非対応。

### Step 2: S3 へのアップロード

```bash
# S3 バケットにアップロード（大容量の場合は multipart）
aws s3 cp ./vm-name-flat.vmdk s3://your-vmimport-bucket/imports/ \
  --region ap-northeast-1

# アップロード確認
aws s3 ls s3://your-vmimport-bucket/imports/vm-name-flat.vmdk
```

### Step 3: import-image の実行

```bash
# import-image コマンドで AMI を作成
aws ec2 import-image \
  --description "VMware to EC2 migration - test-linux-01" \
  --disk-containers "Format=vmdk,UserBucket={S3Bucket=your-vmimport-bucket,S3Key=imports/vm-name-flat.vmdk}" \
  --region ap-northeast-1 \
  --license-type BYOL \
  --architecture x86_64 \
  --platform Linux

# レスポンス例:
# {
#   "ImportTaskId": "import-ami-0123456789abcdef0",
#   "Status": "active",
#   ...
# }
```

**パラメータ解説:**

- `--license-type`: `BYOL`（既存ライセンス持ち込み）または `AWS`（AWS 提供ライセンス）
- `--platform`: `Linux` または `Windows`
- `--architecture`: `x86_64`（ARM の場合は `arm64`）

### Step 4: インポート進捗の確認

```bash
# ステータス確認（完了まで数十分〜数時間かかる）
aws ec2 describe-import-image-tasks \
  --import-task-ids import-ami-0123456789abcdef0 \
  --region ap-northeast-1

# 進捗を定期確認するワンライナー
watch -n 30 "aws ec2 describe-import-image-tasks \
  --import-task-ids import-ami-0123456789abcdef0 \
  --query 'ImportImageTasks[0].{Status:Status,Progress:Progress,StatusMessage:StatusMessage}' \
  --output table"
```

**ステータス遷移:**
`active` → `converting` → `updating` → `completed`

### Step 5: AMI から EC2 インスタンス起動

```bash
# インポート完了後、AMI ID を取得
AMI_ID=$(aws ec2 describe-import-image-tasks \
  --import-task-ids import-ami-0123456789abcdef0 \
  --query 'ImportImageTasks[0].ImageId' \
  --output text)

echo "AMI ID: $AMI_ID"

# EC2 インスタンス起動
aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type m5.large \
  --subnet-id subnet-xxxxxxxx \
  --security-group-ids sg-xxxxxxxx \
  --key-name your-key-pair \
  --region ap-northeast-1 \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=migrated-vm-01}]'
```

### Step 6: 起動後の確認事項

```bash
# SSH 接続確認
ssh -i your-key.pem ec2-user@<instance-ip>

# ドライバ確認（Nitro インスタンスの場合）
lsmod | grep ena          # ENA ネットワークドライバ
lsmod | grep nvme         # NVMe ブロックデバイスドライバ
cat /sys/class/dmi/id/bios_vendor  # AWS であることを確認

# ネットワーク確認
ip addr show
curl -s http://169.254.169.254/latest/meta-data/instance-id
```

---

## VM Import が行う自動修正

AWS VM Import/Export は、インポート時に以下の修正を自動的に適用する:
（[公式: Programmatic modifications](https://docs.aws.amazon.com/vm-import/latest/userguide/import-modify-vm.html)）

- Citrix Xen / AWS PV ドライバのインストール
- ENA ドライバのインストール（Nitro インスタンス対応）
- ブートローダーの修正（GRUB 等）
- ネットワーク設定の調整（DHCP 有効化）
- SSH サーバー設定の確認
- VMware Tools の削除

`--no-modifications` フラグを指定するとこれらの修正をスキップできるが、非推奨。

---

## Windows の場合の追加考慮事項

```bash
# Windows の場合
aws ec2 import-image \
  --description "Windows Server 2022 migration" \
  --disk-containers "Format=vmdk,UserBucket={S3Bucket=your-vmimport-bucket,S3Key=imports/win-vm.vmdk}" \
  --region ap-northeast-1 \
  --license-type BYOL \
  --platform Windows
```

- BYOL の場合: KMS サーバーまたは MAK キーでのアクティベーションが別途必要
- License Included の場合: `--license-type AWS` を指定（AWS のライセンスが適用される）
- Windows Server 2008 は VM Import 非サポート

---

## トラブルシューティング

| エラー | 原因 | 対処 |
|--------|------|------|
| `ClientError: Unsupported image format` | スパース VMDK を指定 | flat/monolithic にエクスポートし直す |
| `ClientError: Invalid S3 source` | S3 キーまたはバケット名が間違い | パス確認 + vmimport ロールの S3 権限確認 |
| `FirstBootFailure` | ブートローダーが EC2 非互換 | `--no-modifications` を外して再試行 |
| 長時間 `converting` で進まない | ディスクサイズが大きい | 正常。100GB あたり 30-60分が目安 |

---

## 所要時間の目安

| ディスクサイズ | S3 アップロード (100Mbps) | Import 処理 | 合計 |
|-------------|-------------------------|------------|------|
| 50 GB | ~70 分 | 30-60 分 | ~2-2.5 時間 |
| 100 GB | ~140 分 | 60-90 分 | ~4-5 時間 |
| 500 GB | ~700 分 | 3-5 時間 | ~15-17 時間 |

> ⚠️ これは VM Import/Export の所要時間であり、Shift Toolkit の FlexClone 変換（数秒〜数分）とは根本的に異なるアプローチ。VM Import はデータの完全コピーが必要。

---

*本手順は Shift Toolkit Early Preview がシナリオ B（OS ディスクは別途 AMI 化）と判明した場合のバックアッププランです。*
