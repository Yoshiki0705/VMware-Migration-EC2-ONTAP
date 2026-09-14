# DR Runbook: オンプレ VMware×ONTAP → EC2×FSx for ONTAP（SnapMirror ベース）

**目的**: オンプレミス VMware/ONTAP 環境のデータを Amazon FSx for NetApp ONTAP へ SnapMirror で継続レプリケーションし、災害時に Amazon EC2 で復旧する DR 手順。

> ⚠️ **スコープと前提（distinction discipline）**
> - 本 runbook は **DR（継続レプリケーション＋復旧）**を対象とする。一度きりの移行（リホスト）は別ドキュメント（Shift Toolkit / AWS Transform 手順）を参照。
> - **AWS Transform は移行サービスであり、継続レプリケーション型 DR のオーケストレーターではない。** DR のデータ複製は SnapMirror が担う。AWS ネイティブ DR を比較検討する場合は AWS Elastic Disaster Recovery (DRS) が候補だが、DRS は EBS ベースで FSx for ONTAP ランディングとは設計が異なる（本 runbook の対象外）。
> - 数値（RPO/RTO 等）は検証で実測する目標値であり、保証値ではない。

---

## 1. DR アーキテクチャ概要

```text
[オンプレ Primary]                         [AWS DR サイト]
VMware ESXi + ONTAP                         Amazon EC2 (待機/オンデマンド起動)
  data volume (NFS/LUN)                       └─ iSCSI attach
        │                                          ▲
        │ SnapMirror (Async)                       │
        └──────────────────────────────────▶ FSx for NetApp ONTAP (Multi-AZ)
                                              destination volume (RW 化で復旧)
```

- **データ複製**: ONTAP SnapMirror（Async）でオンプレ ONTAP → FSx for ONTAP へ増分転送
- **コンピュート**: 平常時は EC2 を起動しない（コスト最小化）。障害時に AMI から起動 or 事前作成インスタンスを起動
- **復旧の鍵**: FSx for ONTAP 側 destination volume を break して RW 化 → LUN を igroup にマップ → EC2 から iSCSI アタッチ

---

## 2. RPO / RTO（検証で実測する目標）

| 指標 | 定義 | 目標（検証で確認） | 主な決定要因 |
|------|------|------------------|------------|
| RPO | データ損失許容時間 | SnapMirror スケジュール間隔（例: 15分〜1時間） | 転送頻度・回線帯域・変更量 |
| RTO | 復旧目標時間 | 例: 30〜60分（小規模） | break→RW、LUN マップ、EC2 起動、iSCSI アタッチ、アプリ起動 |

> **注意**: SnapMirror の初期ベースライン転送は RPO に含めない（DR 稼働前の準備）。RPO は増分転送間隔で決まる。

---

## 3. 事前準備（平常時）

### 3.1 ネットワーク

- オンプレ ONTAP ↔ FSx for ONTAP 間: SnapMirror 用ポート（intercluster LIF、TCP 11104/11105）を VPN/DX 経由で開放
- FSx for ONTAP ↔ EC2: iSCSI（TCP 3260）。詳細は `fsxn-iscsi-setup.md`

### 3.2 SnapMirror 関係の確立（クラスタピアリング → SVM ピアリング → 関係作成）

```text
# オンプレ ONTAP 側（source クラスタ）で実行する例
# 1) クラスタピア作成（FSx for ONTAP 側 intercluster LIF を指定）
cluster peer create -peer-addrs <fsxn-intercluster-lif> -ipspace Default

# 2) SVM ピア作成
vserver peer create -vserver <onprem-svm> -peer-vserver <fsxn-svm> \
  -applications snapmirror -peer-cluster <fsxn-cluster>

# 3) FSx for ONTAP 側（destination）で SnapMirror 関係を作成
snapmirror create -source-path <onprem-svm>:<src_vol> \
  -destination-path <fsxn-svm>:<dst_vol> \
  -type XDP -schedule <schedule_name>

# 4) 初期ベースライン転送
snapmirror initialize -destination-path <fsxn-svm>:<dst_vol>
```

### 3.3 レプリケーション健全性の継続監視

```text
# 関係の状態・遅延（lag）確認
snapmirror show -destination-path <fsxn-svm>:<dst_vol> \
  -fields state,status,lag-time,last-transfer-size
```

- `Healthy=true`、`lag-time` が RPO 目標内であることを定期確認
- CloudWatch / 監視で lag を可視化（しきい値超過でアラート）

---

## 4. フェイルオーバー手順（DR 発動）

```text
# 1) (可能なら) 最終増分を転送して RPO を最小化
snapmirror update -destination-path <fsxn-svm>:<dst_vol>

# 2) SnapMirror 関係を break して destination を RW 化
snapmirror quiesce -destination-path <fsxn-svm>:<dst_vol>
snapmirror break  -destination-path <fsxn-svm>:<dst_vol>

# 3) destination volume の LUN を igroup にマップ（EC2 initiator）
lun mapping create -vserver <fsxn-svm> \
  -path /vol/<dst_vol>/<lun> -igroup <ec2-igroup> -lun-id 0
```

その後 EC2 側で:

1. DR 用 EC2 インスタンスを起動（事前作成 AMI、または起動済み待機インスタンス）
2. iSCSI でターゲット検出・ログイン・マルチパス確認（`fsxn-iscsi-setup.md` Step 5-7）
3. ファイルシステムをマウントし、アプリケーションを起動
4. DNS / ロードバランサ切替で DR サイトへトラフィックを誘導

> **OS/ブートの扱い**: EC2 はデータ（FSx for ONTAP）から起動できない。DR 用 OS は事前に AMI 化しておくか、ゴールデン AMI から起動して FSx for ONTAP の data LUN をアタッチする構成にする。移行（リホスト）と同じ「OS=EBS / データ=FSx for ONTAP」分離原則が DR でも適用される。

---

## 5. フェイルバック手順（プライマリ復旧後）

```text
# 1) 逆方向 resync（DR サイト→オンプレ）で差分を戻す
snapmirror resync -source-path <fsxn-svm>:<dst_vol> \
  -destination-path <onprem-svm>:<src_vol>

# 2) 計画停止で最終同期 → 方向を元に戻す（再度 resync を正方向で確立）
# 3) オンプレで業務再開後、正方向 SnapMirror を再確立
```

> フェイルバックは計画停止を伴う。手順・停止ウィンドウを事前に runbook 化し、DR テストで実測する。

---

## 6. DR テスト（本番断なしの検証）

SnapMirror 関係を壊さずに DR を検証するには **FlexClone** を使う:

```text
# destination の最新 Snapshot から FlexClone を作成（本番レプリは継続）
volume clone create -vserver <fsxn-svm> -flexclone <dst_vol>_drtest \
  -parent-volume <dst_vol> -parent-snapshot <snapshot>

# クローンの LUN を テスト用 EC2 にマップして起動確認
# テスト完了後にクローンを削除
volume clone ... / lun mapping delete ... / volume destroy <dst_vol>_drtest
```

- 本番の SnapMirror を break せずに「起動できるか・データ整合性・RTO」を測定できる
- DR テストは定期実施し、結果を `verification/evidence/` に記録

---

## 7. 検証項目（DR シナリオ）

| # | 検証項目 | 判定基準 | ツール |
|---|---------|---------|-------|
| D1 | SnapMirror 初期転送完了 | baseline 転送成功、Healthy=true | `snapmirror show` |
| D2 | 増分レプリ lag | lag-time が RPO 目標内 | `snapmirror show -fields lag-time` |
| D3 | break→RW 化 | destination が RW、LUN マップ可能 | ONTAP CLI |
| D4 | EC2 起動 + iSCSI アタッチ | 起動成功、マルチパス active | `multipath -ll` |
| D5 | データ整合性 | フェイルオーバー時点の sha256sum 一致 | sha256sum |
| D6 | RTO 実測 | break〜アプリ応答までの時間 | タイムスタンプ |
| D7 | FlexClone DR テスト | 本番レプリ非断で起動確認 | `volume clone` |
| D8 | フェイルバック | 逆方向 resync 成功、データ戻し確認 | `snapmirror resync` |
| D9 | クロスリージョン DR（任意） | 別リージョン FSx for ONTAP へのレプリ | SnapMirror + FSx for ONTAP(DR) |

---

## 8. 撤去手順（3.2 の解除）

**3.2 でピアを作ったなら、撤去でも解除が必要です。** 解除せずに FSx for ONTAP のスタックを
削除すると止まります。姉妹プロジェクトが 2026-09-13 に実測した内容です
（ONTAP 9.18.1P6、ap-northeast-1。
[出典](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/a97a4ec/docs/ja/verification/flexcache-security-style-inheritance.md)）。

> **ホストが生きているうちにピアを解除してください。** 順序を間違えると、解除を打てる唯一の
> ホストを同じスタック削除が先に消します。

### 8.1 正しい順序

```text
# 1) SnapMirror 関係を解除する（宛先側）
snapmirror delete -destination-path <fsxn-svm>:<dest-volume>
snapmirror release -destination-path <fsxn-svm>:<dest-volume>   # source 側

# 2) SVM ピアを解除する（**ホストが生きているうちに**）
vserver peer delete -vserver <onprem-svm> -peer-vserver <fsxn-svm>

# 3) クラスタピアを解除する
cluster peer delete -peer-cluster <fsxn-cluster>

# 4) 手で足した SG ルールを消す（別スタックの SG を参照している ingress）
#    残すと参照先 SG の削除が「依存オブジェクトがある」で落ちます

# 5) スタックを削除する
aws cloudformation delete-stack --stack-name <stack>
```

### 8.2 順序を間違えた場合の復旧

**4 段階あり、後半 2 つは順序を間違えてからしか現れません。**

| 段階 | 症状 |
|---|---|
| 1 | SVM ピアが残っていると FSx for ONTAP は SVM を削除せず、スタックが `svmLifecycle should be DELETING, but get: MISCONFIGURED` で `DELETE_FAILED` になります |
| 2 | **`vserver peer delete` を打てる唯一のホストを、同じスタック削除が先に消します。** 管理 LIF はプライベートアドレスなので、検証ホストが消えると REST でも CLI でも到達できません |
| 3 | ピアを消しても `Lifecycle` は `MISCONFIGURED` のまま残り、**CloudFormation はこの値を見て削除を呼ぶ前に断ります** |
| 4 | 手で足した SG ルールが、参照先 SG の削除を止めます |

復旧の順序:

```text
# 1) ONTAP に到達できるホストを立て直す（t3.micro で足ります）
# 2) ピアを解除する（8.1 の 2〜3）
# 3) **FSx for ONTAP の API で SVM を直接削除する**
#    aws fsx delete-storage-virtual-machine は MISCONFIGURED のままでも受け付け、DELETING に入ります
aws fsx delete-storage-virtual-machine --storage-virtual-machine-id <svm-id>
# 4) スタック削除を再試行する

# 5) 救援ホストは、SVM が消えたことを確認してから消す
#    削除を呼んだだけでは終わっていない。SvmNotFound が返るまでは、
#    ONTAP を覗ける唯一のホストを残す
aws fsx describe-storage-virtual-machines \
  --storage-virtual-machine-ids <svm-id> \
  --query 'StorageVirtualMachines[].Lifecycle' --output text
```

**救援ホストの撤去は最後です。** 姉妹プロジェクトは、不要だと確認する前に救援スタックを消して
**原因を切り分ける経路そのものを失っています**（実測の開示。ONTAP 9.18.1P6、`ap-northeast-1`）。
段階 2 と同じ形が、復旧の側でもう一度現れます。

### 8.3 最終バックアップの残り方

**削除経路によって残るかが変わります。** 姉妹プロジェクトの実測では、CloudFormation が
削除した 2 本には最終バックアップが残り、ONTAP REST で削除した 4 本には残りませんでした。
**撤去後に数えてください。**

```bash
aws fsx describe-backups --query 'Backups[].{Id:BackupId,Vol:Volume.Name,Type:Type}' --output table
```

## 9. リスクと注意

| リスク | 影響 | 対策 |
|--------|------|------|
| SnapMirror lag が RPO 超過 | データ損失増 | スケジュール短縮、帯域増、変更量の多い時間帯回避 |
| break 後の誤操作で resync 不可 | フェイルバック困難 | 手順を runbook 化、DR テストで予行 |
| OS ブート未準備 | RTO 超過 | DR 用 AMI を事前作成・定期更新 |
| iSCSI igroup 未登録 | 復旧時にマップ不可 | EC2 initiator を事前登録、または起動時自動化 |
| コスト誤認 | 想定外課金 | 平常時は EC2 停止。FSx for ONTAP destination 容量・転送は継続課金 |

---

*本 runbook は SnapMirror / FSx for ONTAP 公式ドキュメント（2026年6月時点）に基づく検証用ドラフト。実コマンド・パラメータは検証環境で確認のうえ確定する。*
