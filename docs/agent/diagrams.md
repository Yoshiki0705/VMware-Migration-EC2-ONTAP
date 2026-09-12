# Regenerating the architecture diagrams

Kept out of `AGENTS.md`, which is loaded on every turn and has a byte budget. This is
needed only when a diagram changes, so it costs nothing to look up.

The full standard lives in the user-level steering file `architecture-diagram-standards`.
What follows is only what is specific to this repository, plus the failures that produce a
file which exports *without* the icons — not visible until someone opens the PNG.

## Commands

```bash
make diagrams          # regenerate every .drawio and export SVG + PNG
make diagrams-check    # committed files still match the spec (needs the icon package)
make diagram-assets    # CI-safe: artifacts present, no icons committed, no CJK in EN
```

`make ci` runs `diagram-assets` only, via `drift`. The other two need the AWS Architecture
Icons package and the draw.io desktop app, so they are authoring steps rather than gates.

## Layout

| Artefact | Path |
|---|---|
| Source of truth | `docs/_assets/diagrams/<name>[-en][-dark].drawio` |
| SVG for GitHub | `docs/_assets/images/<name>[-en].svg` |
| PNG for blog posts | `docs/_assets/images/png/<name>[-en][-dark]@2x.png` |

`docs/_assets/` rather than `docs/images/` because the underscore marks the directory as
not-content: this repository's validators walk `docs/**/*.md` and pair `docs/ja/` against
`docs/en/`, and a `-en` suffixed diagram in a content directory confuses that pairing.

There is no dark SVG on purpose. The SVG export carries both themes as CSS `light-dark()`
pairs and the viewer picks, so the light file serves a dark-mode reader too. A PNG cannot
adapt, which is the only reason the dark rasters exist.

Japanese keeps the bare filename. A published blog post links the exported PNG by that
exact path, so renaming it breaks a live image.

## The only method that works for export

Generate the `.drawio` XML directly, with each icon embedded as
`shape=image;image=data:image/svg+xml,<base64>` in the cell's `style` attribute.

Things that do NOT work:

| Approach | Problem |
|---|---|
| draw.io MCP `insert_image_vertex` | Icons render in the editor and disappear on CLI export |
| `mxgraph.aws4.*` service shapes | 2019 icon generation, not the current asset package |
| `data:image/svg+xml;base64,` | draw.io wants the comma-only form; `;base64` exports a blank |
| `xml.sax.saxutils.escape()` on a label | Does not escape `"`. An unescaped quote terminates the attribute and draw.io silently drops that cell **and every cell after it** |

The `mxgraph.aws4.group` *container* shapes are a different thing from the aws4 icon set
and are used: they draw a boundary, not a service mark.

## ONTAP objects have no AWS icon

A Snapshot, a FlexClone, a LUN and a FlexVol are ONTAP mechanisms. The AWS package has
snapshot and volume icons, but they carry the Amazon EBS mark, and putting that mark on an
ONTAP Snapshot says Amazon EBS is doing the work — which is the confusion the FlexClone
figure exists to remove. Name the object in a box instead. Do not substitute another
vendor's mark for a missing icon either; a stand-in attributes the service to whoever's
mark was borrowed.

## Verification is visual

`ET.parse()` passing proves nothing about the picture, and neither does `--check`. Export
the PNG and look at every figure, in each language and each theme separately. Found only
by looking, on the first pass of these two figures: a frame title hidden behind an icon, a
27-character edge label lying across the target's own label, an edge routed straight
through a box it was not connected to, and an icon with no label at all.

`@2x` exports exceed the image read limit. Downscale first:

```bash
sips -Z 1400 docs/_assets/images/png/<name>@2x.png --out /tmp/preview.png
```

## Icon package

Not committed: AWS licenses the assets for use in a diagram, not for redistribution. The
builder resolves it from `--icons`, then `AWS_ICON_PACKAGE`, then the newest
`~/Downloads/Icon-package_*`. The release date is read off the directory name, so a new
quarterly package needs no edit.

A service that shipped recently is absent from an older package. `Arch_AWS-Transform_64.svg`
is in `07312026` and not in `01302026`, so these figures need the newer one.

## ラベルの可読性の下限

`make diagram-fonts` が検査する。数値は `tools/check_diagram_fonts.py` に置いてあり、
規範は `~/.kiro/steering/global-document-readability.md`。

ラベルが表示される大きさは、画像が読者のカラム幅に収まるよう縮小された**後**の大きさで
決まる。したがってキャンバスが広いほど、同じ `fontSize` でも小さく表示される。下限は 2 つで、
両方を満たす必要がある。

| 下限 | 値 | 塞いでいる抜け道 |
|---|---|---|
| 実効サイズ = `fontSize × min(1, 880 / 書き出し幅)` | **14px 以上** | エディタでは読めるが公開ページでは読めないラベル |
| ソースの `fontSize` | **16px 以上** | キャンバスを狭めて実効サイズだけ満たし、文字は小さいまま |

880px は GitHub / dev.to / hatenablog の本文カラム幅。幅は `pageWidth` ではなく書き出した
SVG の幅を使う（draw.io は内容にクロップして `--border` を足すので両者はずれる）。

| キャンバス幅 | 必要な `fontSize` |
|---|---|
| 880px 以下 | 16 |
| 1200px | 20 |
| 1500px | 24 |
| 1600px | 26 |

**キャンバスを広げると必要な font が上がる。** 下限を満たしたまま収まらなくなったときは、
ラベルを 2 行に折る → 補足ボックスを図の外の本文へ出す → キャンバスを 880px 側へ狭めて縦に
積む → 図を分割する → 抽象化する、の順で解決する。**縮小は選択肢に入らない。**

### 下限を満たすまでに要った変更

**負債は残っていない。** `diagram-font-debt.txt` は空になったので削除した。再び下回る図が
出たら検査器がそのまま失敗するので、ファイルを作り直す必要はない（作る場合は
`<パス>` を 1 行ずつ。未記載の違反も、記載されているのに下限を満たすようになったファイルも
失敗する）。

**補足ボックスは全図から削除した。** 載っていた実測値はすべて
`docs/ja|en/atx-fsxn-ga-verification.md` の本文と表にあり、消えたのは事実ではなく二重管理。
`Note` シェイプごと削除したのは、残すことが次の図で文字の壁を画像に入れる誘いになるため。
参照マーカー（`※1`〜`※4`、`*1`〜`*4`）も落とした。**参照先の無い脚注番号はマーカーが無いより悪い。**

3 図でそれぞれ別の手が要った。

| 図 | 変更 | 結果 |
|---|---|---|
| `atx-fsxn-finalize-flexclone` | 横 4 段 → **縦積み** | 925 × 710、実効 15.6px |
| `atx-fsxn-migration-overview` | **データ経路と管理経路に分割**（この名前は廃止） | — |
| `atx-fsxn-data-path` | 5 段の直列を 4 行に折り、配線を右の桁へ寄せた | 800 × 1000、実効 16.0px |
| `atx-fsxn-control-path` | 分割してそのまま横長 | 940 × 520、実効 15.2px |

**分割が必要だった理由。** overview は 5 段の直列と 2 本の並列分岐を持ち、最長ラベルが 16px で
224px ある（「（レプリケーションサーバー）」、`Amazon Elastic Block Store`）。横 1 列に並べると
幅が 1250px を要し、1250px の下限は `fontSize` 20 で、20px ではラベルが 1.25 倍に伸びて幅が
1450px を要する。**上げるほど必要な幅が増えるので固定点が無い。** 縦積みも選べない
（下の節）。残るのは分割だった。

### 縦積みで詰まる点

`Edge` に書いてあるとおり、**ラベルはアイコンの下に置くのでエッジを下方向へ出せない。**
縦の連鎖にすると各エッジが自分のラベルを貫く。したがって行をまたぐエッジは横へ出して
戻る形になり、その通り道が要る。`atx-fsxn-data-path` は右側をその桁に充てている
（ボックスを左へ寄せてある）。**ボックスは `fillColor=none` なので、ボックスの右端から
配線を出すと中の文字と同じ高さを走り、文字を貫いて見える。** ボックスの下にラベルは無いので、
ボックスからは下方向へ出してよい。

### 最下段の高さを決めるラベル

アイコンの下 44px（2 行）がラベルの領域なので、最下段の枠の下端はアイコンではなくラベルの
下端で決まる。720 で足りると思った枠が、カットオーバー先 EC2 の 2 行目を切った。

### EN の別途確認の必要

日本語で収まって英語で溢れる箇所が 3 つあった。`(runs without interruption)` が SVM 枠に触り、
`Amazon Elastic Block Store`（212px）が枠線を 6px はみ出し、`Independent FlexVol after the split`
が列に入らなかった。**JA だけ見て通すと必ず落とす。**

## エッジラベルが落ちる 4 か所

図 4（`atx-fsxn-onprem-to-aws`）と図 5（`atx-fsxn-iscsi-multipath`）を追加したときに出た不具合。
**`diagram-fonts` も `diagram-flow` もこの 4 つを見ない。** どちらもサイズと向きしか読まないので、
書き出した PNG を開くまで分からない。

| 症状 | 原因 | 直し方 |
|---|---|---|
| ラベルが自分のエッジの縦区間を跨ぐ | `offset` の `along` が 0（中点）で、中点が曲がり角そのもの | `along` を源側へ寄せる、または始点と終点の y を揃えて曲がり角を無くす |
| ラベルが枠の境界線の上に載る | 水平区間の中点が境界の位置と一致 | 枠の左端を動かして「線と境界の間」を広げる。線と線の間ではない |
| 2 つのアイコンのラベルが接する | 間隔をアイコン間の距離で決めた | ラベル幅の合計で決める。`Amazon Elastic Block Store` は 2 行でも約 200px |
| 2 行のラベルが上下の箱の枠線に重なる | 箱の間隔が 28px で、2 行が 44px | 箱の間隔をラベルの行数で決める |

**入口が出口より左にあるとエッジは左へ戻る。** `atx-fsxn-iscsi-multipath` の LUN の左辺（740）が
iSCSI LIF の右辺（700）より右にあるのは装飾ではなく、`diagram-flow` を通すための条件。

**同じ辺の同じ点へ 2 本入れると矢頭が重なって 1 本に見える。** `entry_at` の比率を分ける
（`atx-fsxn-onprem-to-aws` の FSx for ONTAP は SnapMirror が 0.75、iSCSI が 0.25）。

## 図の一覧の持ち場

`scripts/check_diagram_assets.py` の `FIGURES` は `build_diagrams.DIAGRAMS` から導出する。
**以前は同じ一覧を書き写していたので、図を 2 つ追加した直後の実行が「3 figures」を返し、
新しい図の成果物が 1 つも無くても `OK` が出た。** 検査器が何を見たかは結果の一部。

## 段の枠を並べるときの 2 点

`atx-fsxn-migration-journey` で出たもの。

**枠の高さを削るとタイトルの帯にアイコンが食い込む。** アイコンの中心を枠の上端 + 90 に置く前提なので、高さ 140 の枠ではタイトル（上端 + 5〜35）とアイコン（上端 + 50 から）が重なった。**段を並べる図では高さを揃える。** 中身が少ない段だけ縮めると、その段だけタイトルが読めなくなる。

**実線の枠は AWS の構成に見える。** `kind="vpc"` の実線は VPC の境界と区別がつかない。段や選択肢のような論理的なまとまりには `dashed=True` を使う。`gr_icon=None` はバッジを出さないだけで、線種までは面倒を見ない。

## ブログ本文の ASCII 図を置き換えたときに出た 3 件

図 7〜10（`atx-fsxn-vmware-pathways` / `-ontap-portability` / `-multiprotocol-volume` /
`-flexclone-blocks`）で出たもの。**3 件とも `diagram-fonts` と `diagram-flow` を通る。**

| 症状 | 原因 | 直し方 |
|---|---|---|
| 枠は出るがバッジだけが出ない | `grIcon=mxgraph.aws4.group_corporate` は存在しない shape 名。draw.io は不明な shape を**無言で描かず、書き出しも成功する** | 正しくは `group_corporate_data_center`。名前は `strings /Applications/draw.io.app/Contents/Resources/app.asar \| grep grIcon=` で確定できる |
| エッジのラベルがアイコンのラベルに重なって 1 つの文字列に見える（`Amazon FSxNFSNetApp ONTAP`） | アイコンをエッジの回廊に置いた。エッジの中点がアイコンのラベルの帯と同じ y に来た | アイコンを回廊の外（クライアントの行より上）へ出す |
| アイコンの真下へ引いた線がそのアイコンのラベルを縦に貫く | **アイコンの下はそのアイコンのラベルの領域。** ラベルはアイコンより広いので、真下に落ちる線は必ず文字を通る | 右へ出してから、ラベルの右端より右の x で落とす |

**エッジのラベルが置ける幅は箱の間隔で決まる。** 図 10 は箱の間隔が 90px で、
`作成はメタデータ操作だけ`（16px で約 192px）が隣の箱に 51px 食い込んだ。間隔を 120px に広げ、
ラベルを `メタデータのみ`（約 112px）に詰めた。**間隔とラベル長は 1 つの決定。**

**境界が事実を壊すなら境界を描かない。** 図 9 は Amazon EC2・VMware ESXi・Hyper-V が
同じ列に縦に並ぶ。AWS Cloud の枠を 1 つ置くと Amazon EC2 が枠の外に出て「AWS の外にある
Amazon EC2」になる。枠を省いてアイコンとラベルに任せた。ボリュームの枠は AWS の境界では
なく ONTAP のボリュームなので残している。

## 検証していない段への公式アイコンの適用

当初この図を Mermaid のままにした。理由は「未検証の将来フェーズに公式アイコンを付けると推測が構成図に見える」で、これは**判断を誤っていた**。読者がサービスを取り違える害の方が大きい。`Amazon ECS / Amazon EKS` のような短縮形の併記も、公式サービス名で書けば消える曖昧さだった。

検証範囲は絵の描き方ではなく、枠のタイトル（`Phase 1: リホスト（本検証の範囲）`）と本文の但し書きで示す。
