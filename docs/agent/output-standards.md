# Output standards

Mirror of the user-level Kiro global steering, kept here so the rules hold even
when steering is not loaded. Enforced by
`.github/workflows/agent-output-audit.yml` (naming, neutrality, leak, parity) and
`.github/workflows/gitleaks.yml` (secrets).

## Naming (NetApp / AWS)

- First mention: **Amazon FSx for NetApp ONTAP**; thereafter **FSx for ONTAP**.
  `FSxN`, bare `FSx`, and `FSx ONTAP` are forbidden. <!-- allow:naming -->
- Access Points: **FSx for ONTAP S3 AP** — not "FSx S3 AP", and not a bare <!-- allow:naming -->
  "S3 AP" where the FSx for ONTAP context matters.
- Do not propose NetApp Workload Factory, NetApp Console, or BlueXP. Reframe to <!-- allow:naming -->
  the native equivalent: Amazon CloudWatch, ONTAP REST API, FabricPool,
  AWS DataSync, Snapshot / FlexClone / SnapMirror.
- Exception: a verbatim external citation title, or a line that has to quote a
  forbidden term in order to forbid it. Annotate it with `<!-- allow:naming -->`.
  The naming, forbidden-tools, and vendor-neutrality checks all honour that one
  marker, so use it on the narrowest line that needs it.

## Vendor neutrality

Present alternatives as options suited to different contexts. Superiority
claims ("best", "beats X", "より優れている", "競合ツール", "優位性", <!-- allow:naming -->
"game-changer", "最強", "最速", "最も高速", "fastest") are forbidden. State <!-- allow:naming -->
trade-offs symmetrically, including the constraints of the option being
recommended.

**A superlative about speed is a superiority claim.** The speed words were added
on 2026-09-14, after a blog draft carried "最も高速なツールです" to within a day of <!-- allow:naming -->
publication: `最強` was on the list and the speed superlative was not, so a claim <!-- allow:naming -->
about performance was the one shape that passed. Adding them turned up four
tracked lines calling one method 推奨・最速, all of them the vendor procedure's <!-- allow:naming -->
own wording, which now says so instead of stating it as ours.

**Attribute, do not delete, when the vendor said it.** "The procedure recommends
this method and describes it as taking less time" keeps the fact and drops the
claim. What the checker rejects is this repository asserting it.

## Public-output safety

Never commit personal or persona names, email addresses, AWS account IDs,
internal IP addresses or hostnames, support case numbers, or vendor-internal
ticket IDs. Use role-based references instead: "Storage Specialist lens",
"Partner SA feedback", "an internal product request (tracked)".

Inline review notes use a neutral topic label (`> **Security note**:`,
`> **コストに関する補足**:`), never a job-title label, which would imply a real
person in that role reviewed the document.

No process metadata in published docs: review rounds, dates, or lens counts
belong in `.private/` (gitignored).

> **Leak-check degradation note**: the leak step builds its pattern from the
> `PROJECT_CONTEXT_NAMES` repository secret. If that secret is unset the pattern
> falls back to internal ticket IDs only, and name detection silently stops
> without failing the job. Confirm the secret is present when relying on this
> check.

## Japanese section headings

Every `##`-or-deeper heading containing Japanese must be a noun phrase. A
heading sits where a label is expected, so a verb-final form, a question form,
or a full predicate reads as a sentence in a label slot.

| Form | Avoid | Use |
|---|---|---|
| Verb-final | 自分の環境で確かめる | 自環境での確認手順 |
| Question | なぜこの区分が必要か | この区分が必要な理由 |
| Predicate (polite) | 記録されない読み取りがあります | 記録されない読み取りの存在 |
| Predicate (negative) | AWS 側からしか消せない | AWS 側からしか消せないボリューム |

Nominalising must not drop the assertion the heading carries. 「監査の 2 つの面と
片方の穴」loses the claim that a gap exists. Keep it with a suffix (`〜の存在` /
`〜の不在` / `〜の成立` / `〜の不成立` / `〜の無効化` / `〜の上限` / `〜の理由`) or a
modifier (`未対応の〜` / `既定で無効な〜`). A heading that survives no suffix is
carrying a sentence — move it into the body.

Out of scope: H1 (the document title, which this repository keeps in-body and
which its own rule defines as a one-line claim), English headings, `#` lines
inside code fences, table cells, and list items.

Narrative, advice whose tone *is* the content, and statements of intent are not
labels, and nominalising them destroys them. Judge by whether the heading works
as an index entry. If it does not, annotate the heading line with
`<!-- allow:heading-style -->` and say in the surrounding prose why it is
narrative.

Enforced by `make headings` (`tools/check_heading_style.py`). The target runs the
detector's own selftest before the repository scan, because a detector whose rule
stopped matching reports an empty result that is indistinguishable from a pass.
Renaming a heading changes its anchor: check `grep -rn '](#'` and `grep -rn '.md#'`
and follow the references in the same commit.

## Bilingual docs

JA is primary, EN must match section structure and count with equivalent inline
notes. Change both in the same commit.

## Before committing docs

```bash
make drift            # 設定の到達性 + 常時ロード予算
gitleaks detect --config .gitleaks.toml --no-git --source .
```
