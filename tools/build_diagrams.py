#!/usr/bin/env python3
"""Generate the architecture diagrams from a spec, one file per language and theme.

Provenance: the machinery here — direct `.drawio` XML generation, icons embedded as
`data:image/svg+xml,<base64>` data URIs, a keyed `LABELS` table with a CJK residue gate,
`--check` against the committed files, and `stabilize_svg()` — follows
`tools/build_diagrams.py` in the sibling repositories `S3-Burst-on-ONTAP-Files` and
`FSx-for-ONTAP-Adoption-Playbook`. Nothing is re-derived here.

Why the XML is written directly rather than through the draw.io MCP tools or the built-in
`mxgraph.aws4.*` service shapes — each was tried in a sibling project and recorded there:

* `insert_image_vertex` embeds icons in a form the draw.io CLI drops on export, so the
  picture is right on screen and empty in the exported file;
* `mxgraph.aws4.*` carries the 2019 icon generation, not the current quarterly package;
* the data URI must be `data:image/svg+xml,<base64>`. Written as the MIME specification
  would suggest, `data:image/svg+xml;base64,`, draw.io renders nothing and the export
  still reports success.

The `mxgraph.aws4.group` *container* shapes are a different thing from the aws4 icon set
and are used: they draw a boundary, not a service mark.

Icons are read from the AWS Architecture Icons package rather than copied in. AWS licenses
the assets for use in a diagram, not for redistribution, so the package stays outside the
repository and the committed artefacts are the generated `.drawio` and the exported
images. `make ci` therefore does not run this; `make diagrams-check` does, locally.

Note on ONTAP objects: an ONTAP Snapshot, a FlexClone and a LUN have no icon in the AWS
package. Borrowing `Res_Amazon-Elastic-Block-Store_Snapshot_48` for an ONTAP Snapshot
would attribute an ONTAP mechanism to Amazon EBS, which is the confusion figure 2 exists
to remove, so they are drawn as named boxes instead.

Run:
  python3 tools/build_diagrams.py --check           # committed files still match the spec
  python3 tools/build_diagrams.py --write           # regenerate every .drawio
  python3 tools/build_diagrams.py --write --export  # and run the draw.io CLI for SVG + PNG
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess  # nosec B404  # fixed argv, never a shell string
import sys
import xml.etree.ElementTree as ET  # nosec B405  # noqa: S405  parses our own output
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = ROOT / "docs" / "_assets" / "diagrams"
IMAGE_DIR = ROOT / "docs" / "_assets" / "images"
PNG_DIR = IMAGE_DIR / "png"

LANGS = ("ja", "en")
THEMES = ("light", "dark")

# Fixed so regeneration is byte-stable. A changing timestamp puts every diagram in every
# diff and hides the edit that mattered.
MODIFIED = "2026-09-05T00:00:00.000Z"
DRAWIO_CLI = Path("/Applications/draw.io.app/Contents/MacOS/draw.io")

# --- icons -------------------------------------------------------------------------------

# Relative to the package root, with `{d}` standing for the release date and `{v}` for the
# Light/Dark variant of the general resource icons. The date appears in every top-level
# directory inside the package and changes quarterly, so it is read off the directory name
# rather than written here.
#
# The `_Light` suffix on the general resource icons is easy to miss: `Res_Disk_48.svg`
# does not exist, `Res_Disk_48_Light.svg` does.
ICONS = {
    "ec2": "Architecture-Service-Icons_{d}/Arch_Compute/64/Arch_Amazon-EC2_64.svg",
    "fsx_ontap": (
        "Architecture-Service-Icons_{d}/Arch_Storage/64/Arch_Amazon-FSx-for-NetApp-ONTAP_64.svg"
    ),
    # Present in the 07312026 package. An older package predating AWS Transform's GA does
    # not carry it, which surfaces as a missing-icon failure rather than a wrong picture.
    "transform": (
        "Architecture-Service-Icons_{d}/Arch_Migration-Modernization/64/Arch_AWS-Transform_64.svg"
    ),
    "ebs": (
        "Architecture-Service-Icons_{d}/Arch_Storage/64/Arch_Amazon-Elastic-Block-Store_64.svg"
    ),
    "privatelink": (
        "Architecture-Service-Icons_{d}/Arch_Networking-Content-Delivery/64/"
        "Arch_AWS-PrivateLink_64.svg"
    ),
    "secrets_manager": (
        "Architecture-Service-Icons_{d}/Arch_Security-Identity/64/Arch_AWS-Secrets-Manager_64.svg"
    ),
    "nlb": (
        "Resource-Icons_{d}/Res_Networking-Content-Delivery/"
        "Res_Elastic-Load-Balancing_Network-Load-Balancer_48.svg"
    ),
    "ebs_volume": ("Resource-Icons_{d}/Res_Storage/Res_Amazon-Elastic-Block-Store_Volume_48.svg"),
    "disk": "Resource-Icons_{d}/Res_General-Icons/Res_48_{v}/Res_Disk_48_{v}.svg",
}

# Native sizes. Rescaling is what the AWS icon guidelines forbid, so the size follows the
# asset: 80 for an architecture (service) icon, 48 for a resource icon.
ICON_SIZE = {
    "ec2": 80,
    "fsx_ontap": 80,
    "transform": 80,
    "ebs": 80,
    "privatelink": 80,
    "secrets_manager": 80,
    "nlb": 48,
    "ebs_volume": 48,
    "disk": 48,
}

# --- palettes ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """Everything the theme changes, icon variant included, so one lookup covers it."""

    variant: str
    background: str
    ink: str
    cloud_stroke: str
    vpc_stroke: str
    box_stroke: str
    frame_stroke: str


PALETTES = {
    "light": Palette(
        variant="Light",
        background="#FFFFFF",
        ink="#232F3E",
        cloud_stroke="#232F3E",
        vpc_stroke="#8C4FFF",
        box_stroke="#232F3E",
        frame_stroke="#666666",
    ),
    "dark": Palette(
        variant="Dark",
        background="#232F3E",
        ink="#FFFFFF",
        cloud_stroke="#FFFFFF",
        vpc_stroke="#C9A0FF",
        box_stroke="#FFFFFF",
        frame_stroke="#B0B8C1",
    ),
}

# --- styles ------------------------------------------------------------------------------

# 可読性の下限。`make diagram-fonts` が検査する。ラベルは画像が読者のカラム幅に縮小された
# *後* の大きさで表示されるので、この 2 つの数値と `Diagram.width` は 1 つの決定である。16 なら
# キャンバスは約 1000px まで、実効サイズ 14px を下回らずに使える。以前は 1480〜1500px の
# キャンバスに 11 と 12 で、読者には約 6.5px で届いていた。
# **数値だけ上げるとラベルが衝突する。** 幅を詰めるところまでが 1 組の変更。
FONT_BODY = 16
FONT_GROUP = 18

GROUP_POINTS = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
    "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]]"
)


def group_style(gr_icon: str | None, stroke: str, ink: str, dashed: bool, size: int) -> str:
    """A boundary. `gr_icon=None` draws no badge, and an empty value draws no text.

    The official Architecture-Group-Icons package defines a badge for a fixed set of
    boundaries — AWS Cloud, Region, VPC, subnets, Auto Scaling group, account, EC2 instance
    contents, corporate data center, Spot Fleet, Greengrass. **There is no badge for a
    storage virtual machine**, so a boundary that is one has to carry none: putting the AWS
    Cloud badge on it says the box is the AWS Cloud.

    A boundary with no badge is named by placing the service's own architecture icon inside
    it. **The icon's name goes underneath the icon, not beside it** — that is where the AWS
    guidelines put an icon label, and an earlier version of the Finalize figure put it to the
    right by raising `spacingLeft`, which reads as a label detached from its icon.
    """
    badge = f"grIcon=mxgraph.aws4.{gr_icon};" if gr_icon else ""
    return (
        f"{GROUP_POINTS};outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
        f"fontSize={size};fontStyle=1;fontColor={ink};shape=mxgraph.aws4.group;"
        f"{badge}strokeColor={stroke};fillColor=none;"
        f"verticalAlign=top;align=left;spacingLeft=30;spacingTop=4;"
        f"dashed={1 if dashed else 0};"
    )


def icon_style(data_uri: str, ink: str, size: int) -> str:
    return (
        "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
        f"labelPosition=center;align=center;imageAspect=1;aspect=fixed;fontSize={size};"
        f"fontColor={ink};image={data_uri};"
    )


def box_style(stroke: str, ink: str, size: int) -> str:
    """A named ONTAP object with no icon in the AWS package.

    A Snapshot, a FlexClone and a LUN are ONTAP mechanisms. The AWS package has snapshot
    and volume icons, but they carry the Amazon EBS mark, and putting that mark on an
    ONTAP Snapshot says Amazon EBS is doing the work. Naming the object in a box states
    what it is without claiming a service.
    """
    return (
        f"rounded=1;whiteSpace=wrap;html=1;strokeColor={stroke};fillColor=none;"
        f"fontColor={ink};fontSize={size};verticalAlign=middle;align=center;"
    )


def frame_style(stroke: str, ink: str, size: int) -> str:
    """A dashed grouping, used where an edge must arrive at a set rather than at one icon."""
    return (
        f"rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor={stroke};"
        f"fillColor=none;fontColor={ink};fontSize={size};verticalAlign=top;align=center;"
        "spacingTop=6;"
    )


def edge_style(ink: str, background: str, size: int) -> str:
    """An edge and its label.

    `labelBackgroundColor` is set explicitly because draw.io's default is an opaque white
    plate behind every edge label. On the dark canvas the plate stays white while the text
    turns white with it, so each label renders as a blank rectangle — visible only in the
    exported PNG, which is why the standard says to look at the picture.
    """
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;"
        f"strokeColor={ink};strokeWidth=1;fontSize={size};fontColor={ink};"
        f"labelBackgroundColor={background};"
    )


def text_style(ink: str, size: int) -> str:
    return (
        "text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;"
        f"fontSize={size};fontStyle=1;fontColor={ink};"
    )


# `<b>` and `<br>` reach draw.io because the cell style carries `html=1`. They are written
# as literal characters and escaped on the way into the attribute; `quoteattr` also escapes
# `"`, which plain `escape()` does not — an unescaped quote inside a value terminates the
# attribute, and draw.io responds by silently dropping that cell and every cell after it
# while still exporting successfully.
# --- labels ------------------------------------------------------------------------------

# U+203B (※) sits outside every CJK block, so a reference marker would otherwise survive
# untranslated into the English file with the residue gate reporting nothing. U+3000-303F
# covers 、。「」 for the same reason.
# `notes1` / `notes2` と `Note` シェイプは削除した。図の中で最も文字数の多い部分であり、
# 画像がカラム幅に縮小されたとき最初に読めなくなる場所でありながら、検索も選択も翻訳も
# スクリーンリーダーでの読み取りもできない。載っていた実測値はすべて
# `docs/ja|en/atx-fsxn-ga-verification.md` の本文と表にあるので、消えたのは事実ではなく
# 二重管理である。**機構ごと消したのは意図的で**、`Note` を残すことは次の図で文字の壁を
# 画像に入れる誘いになる。

CJK = re.compile(r"[\u203b\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]")

# Service and protocol names stay as they are in both languages: the naming rule requires
# the official name, and translating it would break it. Panel titles, footnotes and prose
# are localized.
LABELS: dict[str, dict[str, str]] = {
    # --- figure 4: on-premises VMware to AWS ---------------------------------------
    "onprem": {"ja": "オンプレミス", "en": "On-premises"},
    "vcenter": {"ja": "vCenter Server", "en": "vCenter Server"},
    "esxi": {"ja": "ESXi ホスト", "en": "ESXi host"},
    "onprem_ontap": {
        "ja": "ONTAP\n（NFS データストア）",
        "en": "ONTAP\n(NFS datastore)",
    },
    "shift_toolkit": {
        "ja": "Shift Toolkit\n（Windows）",
        "en": "Shift Toolkit\n(Windows)",
    },
    "source_vm": {
        "ja": "移行元 VM\n（OS / データとも VMDK）",
        "en": "Source VM\n(OS and data as VMDK)",
    },
    "target_ec2_boot": {
        "ja": "Amazon EC2\n（移行先 / Nitro）",
        "en": "Amazon EC2\n(target / Nitro)",
    },
    "ebs_boot": {
        "ja": "Amazon Elastic Block Store\n（ブートディスク）",
        "en": "Amazon Elastic Block Store\n(boot disk)",
    },
    "fsx_data": {
        "ja": "Amazon FSx for NetApp ONTAP\n（iSCSI LUN)",
        "en": "Amazon FSx for NetApp ONTAP\n(iSCSI LUN)",
    },
    "e_snapmirror": {"ja": "SnapMirror", "en": "SnapMirror"},
    # 2 行。オンプレミスの枠は幅 280 で、縦のエッジ（x=160）の右に置ける余地は 140px しか
    # ない。1 行の JA（約 190px）はどこに置いても枠の右辺か線のどちらかに重なる。
    "e_flexclone": {
        "ja": "FlexClone と\nディスク変換",
        "en": "FlexClone and\ndisk conversion",
    },
    "e_iscsi_mp": {"ja": "iSCSI マルチパス", "en": "iSCSI multipath"},
    # --- figure 5: iSCSI multipath -------------------------------------------------
    "fsx_multiaz": {
        "ja": "Amazon FSx for NetApp ONTAP（Multi-AZ）",
        "en": "Amazon FSx for NetApp ONTAP (Multi-AZ)",
    },
    "client_ec2": {
        "ja": "Amazon EC2\n（iSCSI イニシエーター）",
        "en": "Amazon EC2\n(iSCSI initiator)",
    },
    "lif_pref": {
        "ja": "iSCSI LIF\n（優先 AZ）",
        "en": "iSCSI LIF\n(preferred AZ)",
    },
    "lif_standby": {
        "ja": "iSCSI LIF\n（待機 AZ）",
        "en": "iSCSI LIF\n(standby AZ)",
    },
    "lun": {"ja": "LUN", "en": "LUN"},
    # 優先度の数値（50 / 10）は本文にある。**図の中で最も文字数の多い部分が、画像が縮小された
    # ときに最初に読めなくなる。** ここは経路の区別だけを持たせ、値は本文と表に置く。
    # 短くしたのは可読性のためだけではない: Amazon EC2 と iSCSI LIF の水平区間は 140px で、
    # JA の元のラベル（約 230px）はどこに置いてもアイコンか箱に重なる。
    "e_path_active": {"ja": "パス 1（active）", "en": "Path 1 (active)"},
    "e_path_standby": {"ja": "パス 2（standby）", "en": "Path 2 (standby)"},
    # --- figure 1 -------------------------------------------------------------------
    "aws_cloud": {"ja": "AWS クラウド（ap-northeast-1）", "en": "AWS Cloud (ap-northeast-1)"},
    "vpc": {"ja": "利用者の Amazon VPC", "en": "Customer Amazon VPC"},
    "atx": {
        "ja": "AWS Transform\n(for migrations)",
        "en": "AWS Transform\n(for migrations)",
    },
    "source_ec2": {
        "ja": "Amazon EC2\n（移行元 / エージェント）",
        "en": "Amazon EC2\n(source / agent)",
    },
    "repl_ec2": {
        "ja": "Amazon EC2\n（レプリケーションサーバー）",
        "en": "Amazon EC2\n(replication server)",
    },
    "target_ec2": {
        "ja": "Amazon EC2\n（カットオーバー先）",
        "en": "Amazon EC2\n(cutover target)",
    },
    "ebs": {
        "ja": "Amazon Elastic Block Store\n（ブートのステージング）",
        "en": "Amazon Elastic Block Store\n(boot staging)",
    },
    "fsx_staging": {
        "ja": "Amazon FSx for NetApp ONTAP\n（データのステージング）",
        "en": "Amazon FSx for NetApp ONTAP\n(data staging)",
    },
    # 行と列の見出し。図 1 は「行 = インスタンス、列 = 領域」の表として読ませる。
    "row_source": {
        "ja": "移行元（本検証では Amazon EC2）",
        "en": "Source (Amazon EC2 in this verification)",
    },
    "row_staging": {"ja": "ステージング", "en": "Staging"},
    "row_cutover": {"ja": "カットオーバー後", "en": "After cutover"},
    "col_boot": {"ja": "ブート / ルート領域", "en": "Boot / root area"},
    "col_data": {"ja": "データ領域", "en": "Data area"},
    "src_boot": {
        "ja": "Amazon Elastic Block Store\n（ブート 8 GiB）",
        "en": "Amazon Elastic Block Store\n(boot 8 GiB)",
    },
    "src_data": {
        "ja": "Amazon Elastic Block Store\n（データ 4 GiB × 2）",
        "en": "Amazon Elastic Block Store\n(data 4 GiB × 2)",
    },
    "tgt_boot": {
        "ja": "Amazon Elastic Block Store\n（ルート 8 GiB）",
        "en": "Amazon Elastic Block Store\n(root 8 GiB)",
    },
    "tgt_data": {
        "ja": "Amazon FSx for NetApp ONTAP\n（ターゲット FlexVol・iSCSI）",
        "en": "Amazon FSx for NetApp ONTAP\n(target FlexVol / iSCSI)",
    },
    "privatelink": {"ja": "AWS PrivateLink", "en": "AWS PrivateLink"},
    "nlb": {
        "ja": "Network Load Balancer\n（自動作成）",
        "en": "Network Load Balancer\n(auto-created)",
    },
    # 1 行。2 行目に置いていた「（クライアント証明書）」はエッジのラベルと同じことを言って
    # いたので、エッジ側に寄せた。ラベルが 176px から 171px に縮み、縦線を跨がなくなる。
    "secrets_manager": {"ja": "AWS Secrets Manager", "en": "AWS Secrets Manager"},
    # 管理エンドポイントの持ち主。箱の真上にアイコンを置き、その下にこの名前を出すことで、
    # 箱が「どのサービスのエンドポイントか」が矢印を足さずに読める。アイコンから下へ矢印を
    # 引くことはできない（アイコンの下はラベルの場所）ので、上下の隣接で示す。
    "fsx_mgmt": {
        "ja": "Amazon FSx for NetApp ONTAP",
        "en": "Amazon FSx for NetApp ONTAP",
    },
    "mgmt_endpoint": {
        "ja": "ONTAP 管理エンドポイント\nREST API / 443",
        "en": "ONTAP management endpoint\nREST API / 443",
    },
    "control_plane": {"ja": "管理経路", "en": "Control path"},
    "e_agent": {"ja": "ブロックレプリケーション", "en": "Block replication"},
    "e_cutover": {"ja": "カットオーバー", "en": "Cutover"},
    # 矢印は Secrets Manager から AWS Transform へ向く。証明書が流れる向きに合わせると、
    # 矢頭が右下を向いて他の矢印と揃う。逆向き（「証明書を取得」）だと矢頭だけが左上を指す。
    "e_cert": {"ja": "クライアント証明書", "en": "Client certificate"},
    "e_pl": {"ja": "証明書認証", "en": "Certificate auth"},
    # --- figure 2 -------------------------------------------------------------------
    # 2 行。アイコンの下に置くラベルなので、AWS のガイドラインどおり 2 行以内で折り、
    # 単語の途中では切らない。
    "svm": {
        "ja": "Amazon FSx for NetApp ONTAP\n（検証用 SVM）",
        "en": "Amazon FSx for NetApp ONTAP\n(verification SVM)",
    },
    "f2_staging": {
        "ja": "ステージング FlexVol\n物理 8.03 GiB",
        "en": "Staging FlexVol\n8.03 GiB physical",
    },
    "f2_snapshot": {
        "ja": "ボリューム Snapshot\n（MGN の SNAPSHOT フェーズ）",
        "en": "Volume Snapshot\n(the MGN SNAPSHOT phase)",
    },
    "f2_clone": {
        "ja": "ターゲット FlexVol = FlexClone\n物理 35.5 MiB",
        "en": "Target FlexVol = FlexClone\n35.5 MiB physical",
    },
    "f2_split": {
        "ja": "スプリット後の独立した FlexVol\n物理 8.57 GiB",
        "en": "Independent FlexVol after the split\n8.57 GiB physical",
    },
    "f2_deleted": {
        "ja": "ステージング FlexVol は削除",
        "en": "Staging FlexVol is deleted",
    },
    "f2_target_ec2": {
        "ja": "Amazon EC2\n（無停止で稼働）",
        "en": "Amazon EC2\n(runs without interruption)",
    },
    "e_snap": {"ja": "44 秒", "en": "44s"},
    "e_clone": {"ja": "FlexClone 作成", "en": "FlexClone created"},
    "e_split": {"ja": "Finalize: 60 秒未満", "en": "Finalize: under 60s"},
    "e_delete": {"ja": "約 9 分後", "en": "About 9 min later"},
    "e_serve": {"ja": "iSCSI 提供は継続", "en": "iSCSI keeps serving"},
    "phase_snapshot": {"ja": "SNAPSHOT フェーズ", "en": "SNAPSHOT phase"},
    "phase_launch": {"ja": "LAUNCH フェーズ", "en": "LAUNCH phase"},
    "phase_finalize": {"ja": "Finalize", "en": "Finalize"},
}


def label(key: str, lang: str) -> str:
    """Look up a label, refusing to emit Japanese into an English diagram.

    Two failures are caught here rather than by looking at the picture. A spec naming a
    label with no entry stops the build instead of drawing an empty string; and a new
    Japanese label copied into the English column stops it too. The second is the one that
    would otherwise ship: the file renders, the export succeeds, and only a reader who
    does not read Japanese finds out.
    """
    try:
        value = LABELS[key][lang]
    except KeyError as exc:
        raise SystemExit(f"build_diagrams: no {lang} label for {key!r}") from exc
    if lang != "ja" and CJK.search(value):
        raise SystemExit(
            f"build_diagrams: the {lang} label for {key!r} still contains Japanese: {value[:60]!r}"
        )
    return value


# --- spec --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    cid: str
    icon: str
    label: str
    x: int
    y: int


@dataclass(frozen=True)
class Group:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int
    # None draws no badge. See `group_style`: the package has no badge for an SVM, and the
    # default here is the AWS Cloud one, so a boundary that forgets to set this claims to be
    # the AWS Cloud. That is what shipped in the Finalize figure.
    gr_icon: str | None = "group_aws_cloud"
    kind: str = "cloud"
    dashed: bool = False


@dataclass(frozen=True)
class Box:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Text:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Edge:
    cid: str
    source: str
    target: str
    label: str = ""
    # Fixed connection points as (x, y) fractions of the shape. Needed because an edge
    # left to route itself takes the shortest orthogonal path, which is regularly straight
    # through an icon or through the label under it. A label sits *below* its icon box, so
    # an edge must never leave a box downwards.
    exit_at: tuple[float, float] | None = None
    entry_at: tuple[float, float] | None = None
    both_ways: bool = False
    dashed: bool = False
    # (along, dx, dy). `along` runs from -1 at the source to +1 at the target, so the
    # midpoint is 0 — not 0.5. Passing 0.5 puts the label three quarters along, which is
    # how a label ends up on top of the icon it was meant to sit beside.
    offset: tuple[float, int, int] | None = None
    points: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Diagram:
    name: str
    diagram_id: str
    width: int
    height: int
    # 下限が既定。下回る値を持てるのは、レイアウトがまだ下限に対応していない図だけで、
    # その図は diagram-font-debt.txt にも載っている。数値だけ上げるとラベルが衝突するので、
    # 「下限を満たしていない」と「壊れた絵を出荷している」を同時に避けるには、この 2 つが
    # 一緒に動く必要がある。**レイアウトを決めたら、この上書きと負債の行は同じ変更で消える。**
    font_body: int = FONT_BODY
    font_group: int = FONT_GROUP
    groups: tuple[Group, ...] = ()
    frames: tuple[Frame, ...] = ()
    boxes: tuple[Box, ...] = ()
    texts: tuple[Text, ...] = ()
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()

    def filename(self, lang: str, theme: str) -> str:
        # Japanese keeps the bare name: a published blog post links the exported PNG by
        # this exact path, so renaming either file breaks a live image.
        parts = [self.name]
        if lang != "ja":
            parts.append(lang)
        if theme != "light":
            parts.append(theme)
        return "-".join(parts) + ".drawio"


def centred(icon: str, cx: int, cy: int) -> tuple[int, int]:
    half = ICON_SIZE[icon] // 2
    return cx - half, cy - half


def _data_path() -> Diagram:
    """3 台の EC2 それぞれについて、ブート / ルート領域とデータ領域がどこに置かれるか。

    **行がインスタンス、列が領域。** 以前の版は経路（誰が誰に書き込むか）を主役にしていたが、
    それだと「3 台の EC2 に対して Amazon EBS と FSx for ONTAP がどう割り当たっているか」が
    読めない。ステージングを 1 つの枠にまとめたことで、レプリケーションサーバーが何を持って
    いるのかも見えなくなっていた。

    行を移行元 / ステージング / カットオーバー後の 3 段にし、列をブート / ルート領域とデータ
    領域の 2 つに分けると、**ブートの列が 3 段とも Amazon EBS で、データの列だけが FSx for
    ONTAP に変わる**ことが位置で読める。これが記事の主張そのものなので、図の構造が主張と
    一致する。

    Amazon EBS のアイコンが 4 回出るが、これは 4 本の別のボリュームなので重複ではない。
    同じ列に同じアイコンが縦に並ぶこと自体が「ブートは常に EBS」を示している。

    向きは下だけ。段の間の 2 本以外にエッジは無い。アイコンから線を出さないので、アイコンの
    下 46px を使うラベルを線が貫くことがない。所属は枠と列の位置が示す。
    """
    return Diagram(
        name="atx-fsxn-data-path",
        diagram_id="atx-fsxn-data-path",
        # 949px。列幅は 3 つのラベルの実測（224 / 234 / 243）に列間 24px と境界 3 枚分の
        # 余白を足しただけ。実効サイズは 16 × 880/973 = 14.5px。
        width=949,
        height=925,
        groups=(
            Group("aws_cloud", "aws_cloud", 38, 30, 873, 865),
            Group("vpc", "vpc", 63, 90, 823, 780, gr_icon="group_vpc2", kind="vpc", dashed=True),
        ),
        # 段。エッジは 1 つのアイコンではなく段全体に着く。
        frames=(
            Frame("row_source", "row_source", 88, 175, 773, 190),
            Frame("row_staging", "row_staging", 88, 415, 773, 190),
            Frame("row_cutover", "row_cutover", 88, 655, 773, 190),
        ),
        # 列見出し。VPC のラベルは左上（x 93..338、y 96..120）にあるので、x 365 以降・y 125 は
        # ぶつからない。
        texts=(
            Text("col_boot", "col_boot", 365, 125, 200, 34),
            Text("col_data", "col_data", 627, 125, 200, 34),
        ),
        nodes=(
            # 列の中心は 212 / 465 / 727。最長ラベルは col3 の 243px で、枠の右端 861 まで
            # 12px 残る。アイコンの中心 y は各枠の上端 + 80。
            Node("source_ec2", "ec2", "source_ec2", *centred("ec2", 212, 255)),
            Node("src_boot", "ebs", "src_boot", *centred("ebs", 465, 255)),
            Node("src_data", "ebs", "src_data", *centred("ebs", 727, 255)),
            Node("repl_ec2", "ec2", "repl_ec2", *centred("ec2", 212, 495)),
            Node("stg_boot", "ebs", "ebs", *centred("ebs", 465, 495)),
            Node("stg_data", "fsx_ontap", "fsx_staging", *centred("fsx_ontap", 727, 495)),
            Node("target_ec2", "ec2", "target_ec2", *centred("ec2", 212, 735)),
            Node("tgt_boot", "ebs", "tgt_boot", *centred("ebs", 465, 735)),
            Node("tgt_data", "fsx_ontap", "tgt_data", *centred("fsx_ontap", 727, 735)),
        ),
        edges=(
            # 段から段へ下るだけ。x=204（枠幅の 0.15）は左端の EC2 の列で、ラベル帯
            # （y 295..341）より下の区間しか通らない。
            Edge(
                "e1",
                "row_source",
                "row_staging",
                "e_agent",
                exit_at=(0.15, 1),
                entry_at=(0.15, 0),
                offset=(0, 110, 0),
            ),
            Edge(
                "e2",
                "row_staging",
                "row_cutover",
                "e_cutover",
                exit_at=(0.15, 1),
                entry_at=(0.15, 0),
                offset=(0, 110, 0),
            ),
        ),
    )


def _control_path() -> Diagram:
    """How AWS Transform reaches the ONTAP management endpoint, and where the certificate lives.

    Drawn separately because it is the part that surprised: MGN creates a Network Load Balancer
    and a VPC endpoint service inside the customer VPC, and the public documentation describes the
    outcome ("PrivateLink connectivity") without naming the resources. Leaving it out of the data
    path figure is what left the NLB out of cost estimates.

    左から右へ流れる。各ホップは隣接しており、エッジは隣り合うセルの間の水平・垂直だけを
    走る。**以前は右から左だった。** 隣接は保てていたが、矢印が 3 本とも左を向くので、
    読む向きと流れの向きが逆になる。左右を反転（`x' = W - x - width`）すれば余白も隣接も
    そのまま保てるので、反転していなかったこと自体に理由は無い。以前の版が「左から右にすると
    AWS Transform のエッジが管理エンドポイントの箱を横切る」と書いていたのは、VPC を左に
    置いたまま AWS Transform だけを移した場合の話で、図ごと反転すれば起きない。
    """
    return Diagram(
        name="atx-fsxn-control-path",
        diagram_id="atx-fsxn-control-path",
        # 940 not 1000: at 1000 the export is 988px wide and the effective label size lands at
        # 14.3px, which clears the 14px floor by less than a rounding error in the exporter.
        width=940,
        # 525。管理エンドポイントの箱の上に FSx for ONTAP のアイコンとサービス名を積んだ分だけ
        # 520 から縦に伸ばした。縦は幅を争わないので実効サイズは変わらない。
        height=525,
        groups=(
            Group("aws_cloud", "aws_cloud", 25, 30, 890, 465),
            Group(
                "vpc",
                "vpc",
                250,
                90,
                635,
                375,
                gr_icon="group_vpc2",
                kind="vpc",
                dashed=True,
            ),
        ),
        frames=(Frame("control_plane", "control_plane", 265, 140, 605, 290),),
        boxes=(Box("mgmt_endpoint", "mgmt_endpoint", 590, 300, 260, 56),),
        nodes=(
            # Outside the VPC, on the left: both are AWS Transform's own, not the customer's.
            # 中心 130。AWS Transform と AWS PrivateLink の間隔を 140px 取るために左へ寄せて
            # ある。この区間には "Certificate auth"（144px）が載る。**反転前の版は間隔が
            # 90px で、EN のこのラベルが両隣のアイコンに 27px ずつ重なっていた。** JA の
            # 「証明書認証」は 80px なので JA だけ見ると問題が見えない。
            Node("atx", "transform", "atx", *centred("transform", 130, 328)),
            Node(
                "secrets_manager",
                "secrets_manager",
                "secrets_manager",
                *centred("secrets_manager", 130, 160),
            ),
            Node("privatelink", "privatelink", "privatelink", *centred("privatelink", 350, 328)),
            # 中心 490。500 だと "Network Load Balancer"（189px）の右端が管理エンドポイントの
            # 箱（590 から）に 4px 入る。
            Node("nlb", "nlb", "nlb", *centred("nlb", 490, 328)),
            # 管理エンドポイントの箱（[590,850]、中心 720）の真上。矢印は引かない。アイコンの
            # 下はラベルの場所なので下向きに線を出せず、上下の隣接と真ん中揃えで持ち主を示す。
            Node("fsx_mgmt", "fsx_ontap", "fsx_mgmt", *centred("fsx_ontap", 720, 210)),
        ),
        edges=(
            Edge(
                "e_pl_edge",
                "atx",
                "privatelink",
                "e_pl",
                exit_at=(1, 0.5),
                entry_at=(0, 0.5),
                offset=(0, 0, -14),
            ),
            Edge("e9", "privatelink", "nlb", exit_at=(1, 0.5), entry_at=(0, 0.5)),
            Edge("e10", "nlb", "mgmt_endpoint", exit_at=(1, 0.5), entry_at=(0, 0.5)),
            # **Secrets Manager から AWS Transform へ。** 以前は逆向きで「証明書を取得」と
            # 書いていたが、他の 3 本が右を向いている図の中で 1 本だけ矢頭が左上を指すことに
            # なる。証明書が流れる向きに合わせると矢頭が右下を向き、向きが揃う。
            #
            # 縦線は左の余白（x=70）を下る。2 つのアイコンが同じ x に縦に並んでいるので、
            # どちらの向きでも一度は横へ逃げるしかない。破線ではない（破線での意味付けは禁止）。
            #
            # ラベルは along=0.15（y=210）。Secrets Manager のラベル下端 173 と
            # AWS Transform のアイコン上端 238 の間に入る。x は縦線から +105 で、EN の
            # "Client certificate"（162px）でも左端が 94 になり縦線を跨がない。
            Edge(
                "e_cert_edge",
                "secrets_manager",
                "atx",
                "e_cert",
                exit_at=(0, 0.5),
                entry_at=(0, 0.5),
                points=((70, 160), (70, 328)),
                offset=(0.15, 105, 0),
            ),
        ),
    )


def _finalize() -> Diagram:
    """The Snapshot / FlexClone / split lifecycle, which is where the capacity goes.

    Drawn because the numbers invert across Finalize and a reader planning capacity from
    the pre-Finalize figure will under-provision. The three ONTAP objects are boxes rather
    than icons: see `box_style`.

    **縦積みである。** 横に 4 段を並べると図幅は 1480px を要し、その幅では可読性の下限が
    `fontSize` 24 になる。24 でこのラベル（最長は英語の "Independent FlexVol after the
    split"）を横並びの列に収めることはできない。縦は幅を争わないので、キャンバスを読者の
    カラム幅である 880px 側へ寄せられ、`FONT_BODY` で足りる。フェーズ名は左の桁に置き、
    ステージングの削除だけが右へ分岐する。

    **境界は 2 枚ある。** 以前はこの図に境界が 1 枚しかなく、それが `Group` の既定である
    AWS Cloud のバッジを付けたまま「Amazon FSx for NetApp ONTAP（検証用 SVM）」と名乗って
    いた。バッジは雲、ラベルはストレージ — 読者には AWS Cloud の文字が無い雲として届く。
    公式パッケージに SVM のバッジは無いので、SVM 側はバッジもテキストも持たず
    （`gr_icon=None`、値は空）、中に置いた FSx for ONTAP のサービスアイコンの**下**に
    名前を出す。AWS Cloud は外側に 1 枚足した。他の 2 図と同じ構造になる。

    向きは下と右だけ。縦の連鎖が本流で、ステージングの削除だけが右へ分岐する。
    """
    return Diagram(
        name="atx-fsxn-finalize-flexclone",
        diagram_id="atx-fsxn-finalize-flexclone",
        # 955px。内側に境界が 1 枚増えた分（左右 25px ずつ）だけ 925 から広げている。
        # 実効サイズは 16 × 880/979 = 14.4px で下限 14 を上回る。キャンバスを 100px 広げる
        # ごとに全ラベルへ掛かる縮小率が下がるので、空きのあるキャンバスは無料ではない。
        width=955,
        height=880,
        groups=(
            Group("aws_cloud", "aws_cloud", 25, 30, 905, 820),
            # **文字を持たない境界。** SVM の名前はこの中に置いた FSx for ONTAP アイコンの
            # 「下」にある。境界にテキストを持たせて左上のアイコンの横に並べると、アイコンと
            # ラベルが切り離れて見える。幅 855 は英語の "(runs without interruption)" が
            # Amazon EC2 の下で 208px あるためで、850 だと枠線に触った。
            Group("svm", "", 50, 105, 855, 725, gr_icon=None, dashed=True),
        ),
        boxes=(
            Box("f2_staging", "f2_staging", 265, 270, 330, 64),
            Box("f2_snapshot", "f2_snapshot", 265, 410, 330, 64),
            Box("f2_clone", "f2_clone", 265, 540, 330, 64),
            Box("f2_split", "f2_split", 265, 670, 330, 64),
            # 右へ分岐する唯一の枝。ステージングが消えることは本流ではなく副作用なので、
            # 縦の連鎖から外して置く。
            Box("f2_deleted", "f2_deleted", 630, 410, 240, 64),
        ),
        # フェーズ名は左の桁。段の間に挟むと、同じ y にエッジのラベルが来て衝突する。
        # 左端は 75。SVM 境界の内側 25px で、最長の "SNAPSHOT フェーズ"（136px）が収まる。
        texts=(
            Text("phase_snapshot", "phase_snapshot", 75, 350, 170, 48),
            Text("phase_launch", "phase_launch", 75, 550, 170, 48),
            Text("phase_finalize", "phase_finalize", 75, 680, 170, 48),
        ),
        nodes=(
            # SVM 境界の見出し。**ラベルはアイコンの下**（`icon_style` の
            # `verticalLabelPosition=bottom`）。中心 200 は、2 行のラベルが 243px 幅になる
            # ので境界の左端 50 から内側 28px を残す位置。
            Node("f2_svm", "fsx_ontap", "svm", *centred("fsx_ontap", 200, 160)),
            Node("f2_target_ec2", "ec2", "f2_target_ec2", *centred("ec2", 790, 702)),
        ),
        edges=(
            Edge(
                "f1",
                "f2_staging",
                "f2_snapshot",
                "e_snap",
                exit_at=(0.5, 1),
                entry_at=(0.5, 0),
            ),
            Edge(
                "f2",
                "f2_snapshot",
                "f2_clone",
                "e_clone",
                exit_at=(0.5, 1),
                entry_at=(0.5, 0),
            ),
            Edge(
                "f3",
                "f2_clone",
                "f2_split",
                "e_split",
                exit_at=(0.5, 1),
                entry_at=(0.5, 0),
            ),
            # 右へ出てから下へ折れる。ラベルは水平の区間に載せる。縦の区間に載せると
            # ステージングとスナップショットの箱の間で行き場がない。
            # 破線ではない。破線で「本流ではない」を表すのは規約が禁じている（単色プリセット
            # Open Arrow のみ）。この枝が副流であることは、縦の連鎖から外れた位置と
            # 「約 9 分後」というラベルが示している。
            Edge(
                "f4",
                "f2_staging",
                "f2_deleted",
                "e_delete",
                exit_at=(1, 0.5),
                entry_at=(0.5, 0),
                offset=(0, 0, -14),
            ),
            Edge(
                "f5",
                "f2_split",
                "f2_target_ec2",
                "e_serve",
                exit_at=(1, 0.5),
                entry_at=(0, 0.5),
                offset=(0, 0, -14),
            ),
        ),
    )


def _onprem_to_aws() -> Diagram:
    """オンプレミスの VMware から Amazon EC2 + FSx for ONTAP へ。既存 3 図が AWS Transform の
    内側だけを描いているのに対し、この図は**移行元**を含む。

    左に 1 列、右に AWS。オンプレミスの列は上から下へ、vCenter Server → ESXi → 移行元 VM →
    Shift Toolkit → ONTAP。**Shift Toolkit を移行元 VM と ONTAP の間に置いたのは向きのため
    だけではない。** 変換を行う位置がそこなので、読む順序と処理の順序が一致する。

    ONTAP から FSx for ONTAP への SnapMirror が図の背骨。FSx for ONTAP を ONTAP より下に
    置いてあるのは、右へ出て上がると向きの規則を破るため。

    **VM Import/Export のエッジは引いていない。** ブートディスクだけを Amazon Elastic Block
    Store へ運ぶ別経路で、移行元 VM から見て EBS は右上にあり、線を引くと上向きになる。1 本
    落として本文へ移すのは規格が認めている扱いで、代わりにキャプションで触れる。

    Shift Toolkit と ONTAP はサードパーティなので箱で表し、公式アイコンは AWS のサービスに
    だけ使う。
    """
    return Diagram(
        name="atx-fsxn-onprem-to-aws",
        diagram_id="atx-fsxn-onprem-to-aws",
        # 既存図と同じ 940。実効サイズは 16 x 880/964 = 14.6px で下限を超える。
        width=940,
        # 660。FSx for ONTAP のラベルは 2 行あり、アイコン下端 510 から 554 まで伸びる。
        # 枠を 600 で閉じるのは、**目視で下端をラベルが越えていたため**。ゲートは越境を見ない。
        height=660,
        groups=(
            # オンプレミスを 280、AWS を 575 に振った。**アイコンのラベルは箱と違って幅を
            # 指定できず、サービス名の長さがそのまま必要な間隔になる。**「Amazon Elastic
            # Block Store」は 2 行でも約 200px あり、AWS 側が 395px だと EC2 のラベルと
            # 横に並べられない。箱側のテキストは短いので、幅は箱から取って絵に渡す。
            Group("onprem", "onprem", 20, 40, 280, 530, gr_icon=None, kind="vpc", dashed=True),
            Group("aws_cloud", "aws_cloud", 340, 40, 575, 560),
        ),
        boxes=(
            Box("vcenter", "vcenter", 40, 90, 240, 52),
            Box("esxi", "esxi", 40, 170, 240, 52),
            Box("source_vm", "source_vm", 40, 250, 240, 62),
            Box("shift_toolkit", "shift_toolkit", 40, 340, 240, 52),
            # 間隔 47px。**2 行のエッジラベルは 44px 必要で、以前の 28px では上下の箱の枠線に
            # 文字が重なっていた。** 箱の間隔は見た目の余白ではなくラベルの行数で決まる。
            Box("onprem_ontap", "onprem_ontap", 40, 439, 240, 62),
        ),
        nodes=(
            Node("target_ec2", "ec2", "target_ec2_boot", *centred("ec2", 450, 130)),
            # 中心 760。EC2 のラベル右端（約 510）との間に 150px 空く。**以前は 620 と 780 で
            # 160px しか離しておらず、2 つのラベルが接していた。** アイコン間の距離ではなく
            # ラベル幅の合計で決める。
            Node("ebs_boot", "ebs", "ebs_boot", *centred("ebs", 760, 130)),
            # Amazon Elastic Block Store の真下。**以前は Amazon EC2 の真下に置いていたが、
            # そこへ下向きのエッジを引くと線が EC2 自身のラベルを縦に貫く。** アイコンの下は
            # そのアイコンのラベルの領域なので、下へ抜けるのではなく右へ出て降りる。
            Node("fsx_data", "fsx_ontap", "fsx_data", *centred("fsx_ontap", 760, 470)),
        ),
        edges=(
            Edge("e_vc_esxi", "vcenter", "esxi", exit_at=(0.5, 1), entry_at=(0.5, 0)),
            Edge("e_esxi_vm", "esxi", "source_vm", exit_at=(0.5, 1), entry_at=(0.5, 0)),
            Edge("e_vm_shift", "source_vm", "shift_toolkit", exit_at=(0.5, 1), entry_at=(0.5, 0)),
            Edge(
                "e_shift_ontap",
                "shift_toolkit",
                "onprem_ontap",
                "e_flexclone",
                exit_at=(0.5, 1),
                entry_at=(0.5, 0),
                offset=(0, 75, 0),
            ),
            # ラベルは曲がり角（x=560）の手前に置く。**中点は曲がり角そのもので、そこに置くと
            # 文字が縦の区間を跨ぐ。** along を負にして源側へ寄せる。
            Edge(
                "e_sm",
                "onprem_ontap",
                "fsx_data",
                "e_snapmirror",
                exit_at=(1, 0.5),
                entry_at=(0, 0.75),
                points=((560, 470), (560, 490)),
                offset=(-0.38, 0, -14),
            ),
            # 2 本とも Amazon EC2 の右辺から出る。同じ点から出すと重なるので高さを分ける。
            Edge("e_ec2_ebs", "target_ec2", "ebs_boot", exit_at=(1, 0.35), entry_at=(0, 0.35)),
            # 入口は 0.25、SnapMirror は 0.75。**同じ辺の同じ点へ 2 本入れると矢頭が重なって
            # 1 本に見える。** ラベルは縦の区間の右に置く（左は EC2 のラベル、真上は線）。
            Edge(
                "e_ec2_fsx",
                "target_ec2",
                "fsx_data",
                "e_iscsi_mp",
                exit_at=(1, 0.75),
                entry_at=(0, 0.25),
                offset=(0.0, 80, 0),
            ),
        ),
    )


def _iscsi_multipath() -> Diagram:
    """1 つの LUN に 2 本のパス。**ホスト側の multipath がフェイルオーバーの仕組みそのもの**で、
    ストレージ側は複数のパスを見せるところまでという分界線を示す。

    左上から右下へ。Amazon EC2 が左、iSCSI LIF が 2 つ**縦に**並び、LUN が右下。

    **LIF を横に並べて LUN をその下の中央に置くと、右の LIF から LUN へのエッジが左向きに
    なる。** 2 つの対等なノードが 1 つのターゲットへ収束する形は、ターゲットが両方の右下に
    ないかぎり「右か下」を両腕で満たせない。LIF を縦に積んで LUN を右下に置くと 4 本すべてが
    右下へ進む。LIF が同じ x にあることは対等であることの表現でもある。

    優先度は色ではなくエッジのラベルで示す（矢印の色分けは禁止）。パス数は既定でも上限でも
    なく帯域から決める値で、その算術は図ではなく本文にある。
    """
    return Diagram(
        name="atx-fsxn-iscsi-multipath",
        diagram_id="atx-fsxn-iscsi-multipath",
        width=940,
        height=560,
        groups=(
            Group("aws_cloud", "aws_cloud", 25, 30, 890, 495),
            # 左端を 430 に寄せた。**エッジのラベルが置ける場所は、線と線の間ではなく
            # 「線と枠の境界の間」で決まる。** 以前は 290 で、Amazon EC2 のラベル右端（225）
            # から境界までが 65px しかなく、パスのラベルが境界線の上に載っていた。
            Group(
                "fsx_multiaz",
                "fsx_multiaz",
                430,
                150,
                470,
                350,
                gr_icon=None,
                kind="vpc",
                dashed=True,
            ),
        ),
        boxes=(
            Box("lif_pref", "lif_pref", 480, 200, 220, 62),
            Box("lif_standby", "lif_standby", 480, 330, 220, 62),
            # 左辺（740）が iSCSI LIF の右辺（700）より右にある。**入口が出口より左にあると
            # エッジは左へ戻る**ので、この 40px は装飾ではなく向きの条件。
            Box("lun", "lun", 740, 420, 150, 52),
        ),
        # 縦の中心を iSCSI LIF（優先 AZ）と揃えて 231。**揃えるとパス 1 が直線になり、曲がり
        # 角が消える。** 曲がり角があるとラベルがその縦区間を跨ぐ位置に落ちる。
        nodes=(Node("client_ec2", "ec2", "client_ec2", *centred("ec2", 150, 231)),),
        edges=(
            Edge(
                "e_p1",
                "client_ec2",
                "lif_pref",
                "e_path_active",
                exit_at=(1, 0.5),
                entry_at=(0, 0.5),
                offset=(0.0, 0, -14),
            ),
            # **右辺から出る。** 以前は下辺（0.5, 1）から出していて、線が Amazon EC2 自身の
            # ラベルを縦に貫いていた。ラベルはアイコンより広く「（iSCSI イニシエーター）」は
            # x 50 まで伸びるので、縦の区間は x=270 に置く。
            Edge(
                "e_p2",
                "client_ec2",
                "lif_standby",
                "e_path_standby",
                exit_at=(1, 0.75),
                entry_at=(0, 0.5),
                points=((270, 251), (270, 361)),
                offset=(0.55, 0, -14),
            ),
            Edge("e_l1", "lif_pref", "lun", exit_at=(1, 0.5), entry_at=(0, 0.5)),
            Edge("e_l2", "lif_standby", "lun", exit_at=(1, 0.5), entry_at=(0, 0.5)),
        ),
    )


DIAGRAMS = (
    _data_path(),
    _control_path(),
    _finalize(),
    _onprem_to_aws(),
    _iscsi_multipath(),
)

# --- rendering ---------------------------------------------------------------------------


def icon_package(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise SystemExit(f"build_diagrams: --icons {path} is not a directory")
        return path
    env = os.environ.get("AWS_ICON_PACKAGE")
    if env:
        return icon_package(env)
    for candidate in sorted(Path.home().glob("Downloads/Icon-package_*"), reverse=True):
        if candidate.is_dir():
            return candidate
    raise SystemExit(
        "build_diagrams: the AWS Architecture Icons package was not found.\n"
        "  Download the current quarterly release from "
        "https://aws.amazon.com/architecture/icons/ and either leave it in ~/Downloads\n"
        "  or pass --icons <path> / set AWS_ICON_PACKAGE. The package is not committed\n"
        "  here, which is why the generated .drawio files are."
    )


def package_date(package: Path) -> str:
    """The release date in the package directory name, e.g. Icon-package_07312026.<hash>.

    Read rather than configured, so a new quarterly package needs no edit. A name without
    a date is not the package this tool expects, and saying so beats reporting nine
    missing icons.
    """
    match = re.search(r"Icon-package_(\d{8})", package.name)
    if not match:
        raise SystemExit(
            f"build_diagrams: cannot read a release date from {package.name!r}.\n"
            "  Expected a directory named like Icon-package_07312026.<hash>"
        )
    return match.group(1)


def data_uris(package: Path) -> dict[tuple[str, str], str]:
    """Read every icon, per theme, and build its draw.io data URI.

    Keyed by (icon, theme) because the general resource icons ship a Light and a Dark file
    and the dark diagram has to carry the Dark bytes. Service icons have one file and are
    read twice; that costs nothing and keeps the lookup uniform.

    The comma-only URI form is required. `data:image/svg+xml;base64,` exports a
    broken-image placeholder rather than failing, so the export "succeeds" and only
    looking at the picture shows it.
    """
    uris: dict[tuple[str, str], str] = {}
    date = package_date(package)
    for theme in THEMES:
        variant = PALETTES[theme].variant
        for key, relative in ICONS.items():
            resolved = relative.format(d=date, v=variant)
            path = package / resolved
            if not path.is_file():
                raise SystemExit(f"build_diagrams: {resolved} missing from {package}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            uris[(key, theme)] = f"data:image/svg+xml,{encoded}"
    return uris


def render(diagram: Diagram, lang: str, theme: str, uris: dict[tuple[str, str], str]) -> str:
    p = PALETTES[theme]
    suffix = "".join(
        part
        for part in (
            f"-{lang}" if lang != "ja" else "",
            f"-{theme}" if theme != "light" else "",
        )
    )
    name = f"{diagram.name}{suffix}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<mxfile host="app.diagrams.net" modified="{MODIFIED}" '
            'agent="build_diagrams.py" version="24.0.0" type="device">'
        ),
        f'  <diagram id="{diagram.diagram_id}{suffix}" name="{name}">',
        (
            '    <mxGraphModel dx="1422" dy="762" grid="1" gridSize="10" guides="1" '
            'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{diagram.width}" pageHeight="{diagram.height}" '
            f'background="{p.background}" math="0" shadow="0">'
        ),
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    def vertex(cid: str, value: str, style: str, x: int, y: int, w: int, h: int) -> None:
        lines.append(
            f"        <mxCell id={quoteattr(cid)} value={quoteattr(value)} "
            f'style={quoteattr(style)} vertex="1" parent="1">'
        )
        lines.append(
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />'
        )
        lines.append("        </mxCell>")

    for group in diagram.groups:
        stroke = p.cloud_stroke if group.kind == "cloud" else p.vpc_stroke
        vertex(
            group.cid,
            label(group.label, lang) if group.label else "",
            group_style(group.gr_icon, stroke, p.ink, group.dashed, diagram.font_group),
            group.x,
            group.y,
            group.width,
            group.height,
        )
    # Frames before nodes so the icons draw on top of the container they sit in.
    for frame in diagram.frames:
        vertex(
            frame.cid,
            label(frame.label, lang),
            frame_style(p.frame_stroke, p.ink, diagram.font_body),
            frame.x,
            frame.y,
            frame.width,
            frame.height,
        )
    for box in diagram.boxes:
        vertex(
            box.cid,
            label(box.label, lang),
            box_style(p.box_stroke, p.ink, diagram.font_body),
            box.x,
            box.y,
            box.width,
            box.height,
        )
    for text in diagram.texts:
        vertex(
            text.cid,
            label(text.label, lang),
            text_style(p.ink, diagram.font_body),
            text.x,
            text.y,
            text.width,
            text.height,
        )
    for node in diagram.nodes:
        size = ICON_SIZE[node.icon]
        vertex(
            node.cid,
            label(node.label, lang) if node.label else "",
            icon_style(uris[(node.icon, theme)], p.ink, diagram.font_body),
            node.x,
            node.y,
            size,
            size,
        )
    for edge in diagram.edges:
        style = edge_style(p.ink, p.background, diagram.font_body)
        if edge.exit_at is not None:
            style += f"exitX={edge.exit_at[0]};exitY={edge.exit_at[1]};exitDx=0;exitDy=0;"
        if edge.entry_at is not None:
            style += f"entryX={edge.entry_at[0]};entryY={edge.entry_at[1]};entryDx=0;entryDy=0;"
        if edge.both_ways:
            style += "startArrow=open;startFill=0;"
        if edge.dashed:
            style += "dashed=1;dashPattern=8 4;"
        value = label(edge.label, lang) if edge.label else ""
        lines.append(
            f"        <mxCell id={quoteattr(edge.cid)} value={quoteattr(value)} "
            f'style={quoteattr(style)} edge="1" source={quoteattr(edge.source)} '
            f'target={quoteattr(edge.target)} parent="1">'
        )
        # `points` used to be accepted by the dataclass and never written, so every waypoint in
        # every spec was silently discarded and draw.io routed each edge itself. It looked fine
        # wherever its own choice happened to match, and produced an edge straight through the
        # middle of a transparent box where it did not — visible only in the export. A field that
        # is read but not emitted is worse than a missing one: the spec says one thing and the
        # picture shows another. `--check` cannot catch it either, since it compares the written
        # file against the same renderer.
        geometry = []
        if edge.offset is not None:
            along, dx, dy = edge.offset
            geometry.append(f'            <mxPoint as="offset" x="{dx}" y="{dy}" />')
        if edge.points:
            geometry.append('            <Array as="points">')
            geometry += [f'              <mxPoint x="{x}" y="{y}" />' for x, y in edge.points]
            geometry.append("            </Array>")
        if geometry:
            along = edge.offset[0] if edge.offset is not None else None
            attrs = "" if along is None else f'x="{along}" '
            lines.append(f'          <mxGeometry {attrs}relative="1" as="geometry">')
            lines += geometry
            lines.append("          </mxGeometry>")
        else:
            lines.append('          <mxGeometry relative="1" as="geometry" />')
        lines.append("        </mxCell>")

    lines += ["      </root>", "    </mxGraphModel>", "  </diagram>", "</mxfile>", ""]
    return "\n".join(lines)


# --- checking ----------------------------------------------------------------------------


def cells(xml: str) -> list[tuple[str, str, str, str]]:
    """Reduce a document to the parts a reader sees, so formatting is not compared."""
    out = []
    root = ET.fromstring(xml).find(".//root")  # nosec B314  our own generated file
    if root is None:
        raise SystemExit("build_diagrams: no <root> in the document")
    for cell in root.iter("mxCell"):
        geometry = cell.find("mxGeometry")
        geo = (
            " ".join(f"{k}={v}" for k, v in sorted(geometry.attrib.items()))
            if geometry is not None
            else ""
        )
        style = re.sub(
            r"image=data:image/svg\+xml,([A-Za-z0-9+/=]{16})[A-Za-z0-9+/=]*",
            r"image=<\1...>",
            cell.get("style") or "",
        )
        out.append((cell.get("id") or "", cell.get("value") or "", style, geo))
    return out


def check(uris: dict[tuple[str, str], str]) -> int:
    problems = 0
    for diagram in DIAGRAMS:
        for lang in LANGS:
            for theme in THEMES:
                path = DIAGRAM_DIR / diagram.filename(lang, theme)
                if not path.is_file():
                    print(f"  missing   {path.relative_to(ROOT)}", file=sys.stderr)
                    problems += 1
                    continue
                want = cells(render(diagram, lang, theme, uris))
                got = cells(path.read_text(encoding="utf-8"))
                if want == got:
                    continue
                problems += 1
                print(f"  differs   {path.relative_to(ROOT)}", file=sys.stderr)
                for a, b in zip(want, got, strict=False):
                    if a != b:
                        print(f"      spec: {a}", file=sys.stderr)
                        print(f"      file: {b}", file=sys.stderr)
                if len(want) != len(got):
                    print(
                        f"      cell count spec={len(want)} file={len(got)}",
                        file=sys.stderr,
                    )
    if problems:
        print(
            "\n  A generated diagram was edited by hand, or the spec moved without a "
            "regenerate.\n  Run: python3 tools/build_diagrams.py --write --export",
            file=sys.stderr,
        )
        return 1
    print(f"diagrams: {len(DIAGRAMS) * len(LANGS) * len(THEMES)} file(s) match the spec")
    return 0


# --- exporting ---------------------------------------------------------------------------

# draw.io stamps a fresh random element id into every SVG export and uses it twice. Left
# alone, re-exporting an unchanged diagram still produces a one-line diff in every SVG,
# which is the same failure the fixed MODIFIED timestamp exists to prevent: the files that
# did not change bury the one that did.
SVG_RANDOM_ID = re.compile(r"ge-svg-[A-Za-z0-9_-]+")


def stabilize_svg(target: Path) -> None:
    text = target.read_text(encoding="utf-8")
    stabilized = SVG_RANDOM_ID.sub(f"ge-svg-{target.stem}", text)
    if stabilized != text:
        target.write_text(stabilized, encoding="utf-8")


def export(diagram: Diagram, lang: str, theme: str) -> None:
    source = DIAGRAM_DIR / diagram.filename(lang, theme)
    stem = source.stem
    if not DRAWIO_CLI.is_file():
        print(f"  draw.io CLI not found at {DRAWIO_CLI}; skipping export", file=sys.stderr)
        return
    runs: tuple[tuple[Path, list[str]], ...] = (
        # PNG at 2x for the blog posts, which do not render SVG reliably. Both themes get
        # one: a raster cannot adapt to the reader's colour scheme.
        (PNG_DIR / f"{stem}@2x.png", ["--format", "png", "--scale", "2"]),
    )
    if theme == "light":
        # One SVG per figure and language. draw.io writes colours as CSS light-dark()
        # pairs, so the light export already serves a dark-mode viewer; a second SVG from
        # the dark source would hand a dark-mode reader an inverted (light) picture.
        runs = ((IMAGE_DIR / f"{stem}.svg", ["--format", "svg", "--embed-svg-images"]),) + runs
    for target, extra in runs:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # nosec B603  fixed binary, no shell
            [
                str(DRAWIO_CLI),
                "--export",
                "--border",
                "12",
                *extra,
                "--output",
                str(target),
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        if not target.is_file() or target.stat().st_size == 0:
            raise SystemExit(f"build_diagrams: export produced nothing: {target}")
        if target.suffix == ".svg":
            stabilize_svg(target)
        print(f"  exported  {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the .drawio files")
    parser.add_argument("--export", action="store_true", help="also export SVG and PNG")
    parser.add_argument("--check", action="store_true", help="compare committed files to the spec")
    parser.add_argument("--icons", help="path to the AWS Architecture Icons package")
    args = parser.parse_args()

    if not (args.write or args.check):
        parser.error("give --write or --check")

    uris = data_uris(icon_package(args.icons))

    if args.check:
        return check(uris)

    DIAGRAM_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for diagram in DIAGRAMS:
        for lang in LANGS:
            for theme in THEMES:
                path = DIAGRAM_DIR / diagram.filename(lang, theme)
                xml = render(diagram, lang, theme, uris)
                path.write_text(xml, encoding="utf-8")
                # A parse gate, because a broken attribute makes draw.io drop that cell
                # and every cell after it while still exporting successfully.
                try:
                    ET.parse(path)  # nosec B314  our own generated file
                except ET.ParseError as error:
                    raise SystemExit(
                        f"build_diagrams: {path} is not well-formed: {error}"
                    ) from error
                # Counting the list we built would report success even when a cell never
                # landed. Assert presence in what was written.
                for cid in (
                    [c.cid for c in diagram.groups]
                    + [c.cid for c in diagram.frames]
                    + [c.cid for c in diagram.boxes]
                    + [c.cid for c in diagram.texts]
                    + [c.cid for c in diagram.nodes]
                    + [c.cid for c in diagram.edges]
                ):
                    if f'id="{cid}"' not in xml:
                        raise SystemExit(f"build_diagrams: cell {cid!r} missing from {path}")
                # Assert the waypoints reached the file, not that the spec listed them. They were
                # dropped for as long as the field existed, and the only symptom was a line
                # crossing a transparent box in the export.
                wanted = sum(len(edge.points) for edge in diagram.edges)
                got = xml.count("<mxPoint x=")
                if wanted != got:
                    raise SystemExit(
                        f"build_diagrams: {path.name} carries {got} waypoint(s), spec has {wanted}"
                    )
                print(f"  wrote     {path.relative_to(ROOT)}")
                if args.export:
                    export(diagram, lang, theme)
        for group in diagram.groups:
            # A boundary can carry no text (the SVM one does not), and counting "" as a
            # label makes the reported count disagree with the table for no reason.
            if group.label:
                seen.add(group.label)
        for collection in (diagram.frames, diagram.boxes, diagram.texts):
            for item in collection:
                seen.add(item.label)
        for node in diagram.nodes:
            if node.label:
                seen.add(node.label)
        for edge in diagram.edges:
            if edge.label:
                seen.add(edge.label)

    # A mapping nothing uses is a mapping nobody maintains, and the next reader cannot
    # tell a stale entry from one whose figure is still to come.
    unused = sorted(set(LABELS) - seen)
    if unused:
        for key in unused:
            print(f"  unused LABELS entry: {key!r}", file=sys.stderr)
        raise SystemExit(f"{len(unused)} LABELS entr(ies) match no label in any figure")

    stray = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and re.match(r"(Arch_|Res_|Icon-package)", path.name)
        and not {".venv", ".git", "node_modules"} & set(path.parts)
    ]
    if stray:
        raise SystemExit(f"build_diagrams: icon-library files must not be committed: {stray[:5]}")

    print(f"diagrams: OK ({len(seen)} distinct labels, {len(LABELS)} in LABELS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
