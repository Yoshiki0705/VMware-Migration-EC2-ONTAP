# VMware to EC2 + FSx for ONTAP 移行パス検証

[![CI](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/ci.yml/badge.svg)](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/ci.yml)
[![Gitleaks](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/Yoshiki0705/VMware-Migration-EC2-ONTAP/actions/workflows/gitleaks.yml)

🌐 **Language / 言語**: 日本語 (このページ) | [English](README.en.md)

> VMware ESXi → Amazon EC2 + Amazon FSx for NetApp ONTAP 移行を複数パスで実機検証するプロジェクト。
> 既存 ONTAP 運用モデルを AWS に引き継ぎつつ、クラウドネイティブな拡張性・コスト最適化を確認します。

## はじめかた

| やりたいこと | ガイド | 所要時間 |
|:------------|:------|:---------|
| 移行方式を比較したい | [移行方式比較表](docs/ja/migration-method-comparison.md) | 10 min |
| ストレージ費用を比較したい | [費用の比較](docs/ja/tco-comparison.md) | 10 min |
| ONTAP 機能を選定要素として見たい | [機能と選定要素](docs/ja/ontap-capability-selection-factors.md) | 10 min |
| Shift Toolkit で移行したい | [Shift Toolkit 手順書](docs/ja/shift-toolkit-ec2-procedure.md) | 30 min |
| AWS Transform で移行したい | [AWS Transform 手順書](docs/ja/aws-transform-migration-procedure.md) | 30 min |
| VM Import/Export で移行したい | [VM Import 手順書](docs/ja/vm-import-procedure.md) | 20 min |
| PoC 環境を構築したい | [クイックスタート](docs/ja/quickstart.md) | 15 min |
| iSCSI LUN を設定したい | [iSCSI セットアップ](docs/ja/fsxn-iscsi-setup.md) | 15 min |

**解説記事**（シリーズ「AWS モダナイゼーションのデータ基盤」）

| 回 | 日本語 | English |
|:---|:------|:--------|
| 第 1 回 | [VMware 移行を入口に AWS モダナイゼーションを設計する〜データ基盤に FSx for ONTAP を選ぶ理由〜](https://hakobiya.hatenablog.com/entry/fsxn-vmware-migration-options-ec2) | [dev.to](https://dev.to/aws-builders/designing-aws-modernization-with-vmware-migration-as-the-entry-point-why-fsx-for-ontap-as-the-3k24) |
| 第 2 回 | [AWS Transform が FSx for ONTAP へのブロックストレージ移行をサポート — EC2 ソースでの実機検証](https://hakobiya.hatenablog.com/entry/fsxn-aws-transform-mgn-migration-target) | [dev.to](https://dev.to/aws-builders/aws-transform-now-supports-block-storage-migration-to-fsx-for-ontap-benefits-and-pitfalls-from-a-1hhe) |

第 2 回の元になった検証の詳細は [AWS Transform の FSx for ONTAP サポート GA 検証レポート](docs/ja/atx-fsxn-ga-verification.md) にあります。移行の先の段階（コンテナ化・サーバーレス・DR・運用）の読み方は、Hub の [モダナイゼーション旅程マップ](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/reference/modernization-journey-map.md) にまとめています。

> **移行ランブックに載らない前提**（切り戻せる時点、Finalize の容量ピーク、ACL 保持、LUN 配置と復旧の粒度）は、姉妹リポジトリの [FSx for ONTAP Adoption Playbook — 03 移行](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/playbooks/03-migrate/README.md) にあります。ここでは複製せず参照します。
> **ブロックの IOPS / スループットの実測**（4 KiB ランダムが条件でどう動くか、iSCSI と NVMe/TCP の差）は、姉妹リポジトリの [S3-Burst-on-ONTAP-Files — perf-matrix](https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files/blob/main/docs/ja/verification/perf-matrix-results.md) にあります。このプロジェクトは移行経路の検証で、ブロック性能は測っていません。**達成 IOPS は特定の 1 台・特定の条件での値であり、サービスの上限ではありません。** 同じプロビジョンド値でもキャッシュの温まり方で達成値は大きく動き、プロビジョンド値を超える測定もあります（[AWS も「実際の IOPs はプロビジョニングされた IOPs を大幅に上回ることがある」と明記](https://aws.amazon.com/jp/blogs/news/san-a-million-iops-in-aws-from-amazon-fsx-netapp-ontap/)）。選定要素としての位置づけは [ONTAP 機能を選定要素として扱う](docs/ja/ontap-capability-selection-factors.md#ブロックで移行するときに先に効く前提) にまとめています。

<details><summary>📂 全ドキュメント一覧</summary>

| ドキュメント | 概要 |
|:------------|:-----|
| [調査レポート](docs/ja/research.md) | 技術調査・ツール比較 |
| [AD 統合ガイド](docs/ja/ad-integration-for-migration.md) | Active Directory 連携パターン |
| [DR SnapMirror Runbook](docs/ja/dr-snapmirror-runbook.md) | SnapMirror を使った DR 設計 |
| [PoC 計画テンプレート](docs/ja/poc-plan-template.md) | 成功指標・検証計画 |
| [NetApp Q&A](docs/ja/netapp-questions.md) | NetApp 側への確認事項 |

</details>

## アーキテクチャ

```text
[オンプレミス]                          [AWS]
VMware ESXi                            Amazon EC2 (Nitro)
  └── VM (VMDK on ONTAP NFS)             ├── Boot: EBS gp3
                                         └── Data: FSx for ONTAP (iSCSI LUN)

Path A ─ Shift Toolkit: FlexClone 変換 → SnapMirror → EBS AMI → EC2 起動
Path B ─ AWS Transform: Discovery → Wave Plan → MGN レプリケーション → カットオーバー
```

| 条件 | 適したツール |
|:-----|:------------|
| ONTAP 未使用 / EBS のみで十分 | AWS MGN |
| ONTAP 使用中 + 中小規模 | Shift Toolkit (Early Preview) |
| ONTAP 使用中 + 100+ VM + ゼロダウンタイム | Cirrus Migrate Cloud |
| AWS ネイティブで一気通貫 / ソース混在 | AWS Transform (Public Preview) |

<details><summary>⚠️ 制約・注意事項</summary>

| 項目 | 内容 |
|:-----|:-----|
| Shift Toolkit | Early Preview — NetApp 側での有効化が必要 |
| AWS Transform | FSx for ONTAP 宛先は Public Preview — リージョン/UI 変更あり |
| 仕様変更 | いずれも GA 仕様として扱わないこと |
| リージョン | 東京 (ap-northeast-1) で検証 |
| 接続 | VPN or Direct Connect が必要（オンプレ ↔ AWS） |

詳細: [PoC 計画テンプレート](docs/ja/poc-plan-template.md)

</details>

<details><summary>📚 関連リンク</summary>

**NetApp**

- [Shift Toolkit (MySupport — ログイン要)](https://mysupport.netapp.com/site/tools/tool-eula/netapp-shift-toolkit)
- [Migrate VMware to EC2 & iSCSI-based FSx for ONTAP (Blog)](https://www.netapp.com/blog/aws-fsxn-blg-migrate-vmware-to-amazon-ec2-iscsi-based-fsx-for-ontap/)
- [Simplify VM migration with Shift Toolkit (Blog)](https://www.netapp.com/blog/simplify-vm-migration-shift-toolkit/)

**AWS**

- [AWS Transform: VMware to FSx for ONTAP (What's New)](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/aws-transform-vmware-fsx-for-ontap-preview/)
- [Accelerating VMware migration: AWS Transform (Blog)](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-vmware-migration-aws-transforms-new-experience/)
- [Seamless VMware Migration (Storage Blog)](https://aws.amazon.com/blogs/storage/seamless-migration-from-any-vmware-environment-to-amazon-fsx-for-netapp-ontap-and-amazon-ec2/)
- [Amazon FSx for NetApp ONTAP](https://aws.amazon.com/fsx/netapp-ontap/)
- [AWS Transform Pricing](https://aws.amazon.com/transform/pricing/)

</details>

<details><summary>🔧 開発者向け</summary>

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

環境構築の詳細: [クイックスタート](docs/ja/quickstart.md)

</details>

## License

MIT

---

🌐 **Language / 言語**: 日本語 (このページ) | [English](README.en.md)
