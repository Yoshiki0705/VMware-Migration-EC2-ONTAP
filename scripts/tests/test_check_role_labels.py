"""The role-label guard must reject labels that claim a job title, in both languages.

A label like `> **Storage Specialist lens**:` reads as though someone in that role
reviewed the document. Usually nothing of the sort happened, so the label misstates
where the finding came from. The finding itself is fine; only the label is wrong.

**Banning the lens words alone does not work.** 観点 and 視点 are ordinary Japanese;
a rule that fires on "セキュリティの観点から" gets an allow marker attached and then
guards nothing. The condition is therefore a **role token and a lens word in the same
label**, and both directions are asserted here — the rule has to fire on the label
form and stay quiet on the prose form.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "check_role_labels.py"

sys.path.insert(0, str(SCRIPT.parent))
import check_role_labels as labels  # noqa: E402

# ---------------------------------------------------------------- block


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("## 前提の整理（Storage Specialist 観点）", id="heading-ja-kanten"),
        pytest.param("### 設計判断（Security Engineer レンズ）", id="heading-ja-lens"),
        pytest.param("> **AppSec レンズ**: 権限を絞る", id="callout-ja"),
        pytest.param("> **Storage Specialist lens**: capacity", id="callout-en"),
        pytest.param("**Data Protection Officer の視点**: 保持期間", id="bold-label-ja"),
        pytest.param("#### 3b. 検証（VMware Specialist 観点）", id="numbered-heading"),
    ],
)
def test_role_label_is_rejected(text: str) -> None:
    assert labels.violations(text), f"should have been flagged: {text!r}"


# ---------------------------------------------------------------- allow


@pytest.mark.parametrize(
    "text",
    [
        # A lens word with no role token is an ordinary topic label.
        pytest.param("## コストの観点から見た選択", id="lens-word-only"),
        pytest.param("#### 3d. コスト検証（FinOps 観点）", id="discipline-not-a-role"),
        pytest.param("> **Cost note**: セキュリティの観点からも確認します。", id="prose-lens-word"),
        # A role token with no lens word is a normal noun.
        pytest.param("## Architecture", id="role-word-only"),
        pytest.param("> **Security note**: 権限を絞る", id="neutral-topic-label"),
        # Prose is not a label. Only headings and leading bold runs are.
        pytest.param("Storage Specialist の観点から書かれた記事。", id="prose-not-a-label"),
        # A fenced example quotes the forbidden form; it is not a published label.
        # This is the deliberate opposite of check_repo_names.py, where a fenced
        # clone URL is exactly what has to be caught because a reader runs it.
        pytest.param("```markdown\n> **Storage Specialist レンズ**: x\n```", id="fenced-example"),
        pytest.param(
            "## 例（Storage Specialist 観点）<!-- allow:role-label -->", id="allow-marker"
        ),
    ],
)
def test_acceptable_label_is_not_rejected(text: str) -> None:
    assert not labels.violations(text), f"should not have been flagged: {text!r}"


# ---------------------------------------------------------------- boundaries


@pytest.mark.parametrize(
    "text",
    [
        # A token inside a longer, unrelated word. Measured false positives before
        # the boundaries were made two-sided: four of them, one family.
        pytest.param("## 設計（Engineering 観点）", id="engineer-in-engineering"),
        pytest.param("## Architecture の観点", id="architect-in-architecture"),
        pytest.param("## Architectural 判断の観点", id="architect-in-architectural"),
        pytest.param("## エンジニアリングの観点", id="ja-engineer-in-engineering"),
        pytest.param("## USA 市場の観点", id="sa-in-usa"),
        # `[^A-Za-z]` treats `_` as a boundary, which is looser than `\b` and reads
        # an identifier as prose. The class excludes digits and `_` for that reason.
        pytest.param("## FSx_SA_note の観点", id="abbreviation-inside-identifier"),
    ],
)
def test_token_inside_a_longer_word_is_not_a_role(text: str) -> None:
    assert not labels.violations(text), f"false positive: {text!r}"


def test_plural_is_a_person_and_gerund_is_a_field() -> None:
    """`Engineers` are people; `Engineering` is a field. Only `s?` is allowed."""
    assert labels.violations("## 前提（Engineers 観点）")
    assert not labels.violations("## 設計（Engineering 観点）")


def test_boundary_holds_without_whitespace() -> None:
    """Japanese has no word spaces, so `\\b` never fires next to a CJK character."""
    assert labels.violations("## 前提（SA観点）")
    assert labels.violations("> **SREレンズ**: x")


# ---------------------------------------------------------------- mutation


def _mutate(pattern_source: str) -> re.Pattern[str]:
    return re.compile(pattern_source)


def test_one_sided_boundary_would_reintroduce_false_positives() -> None:
    """Each guard must be load-bearing, not decorative.

    Dropping the left lookbehind reintroduces the `USA` family; dropping the
    right lookahead reintroduces the `Engineering` family. Asserting that the
    current pattern passes says nothing about which part of it is doing the work.
    """
    titles = "|".join(labels._TITLES)
    abbrev = "|".join(labels._ABBREVIATIONS)

    right_only = _mutate(rf"(?:{titles})s?{labels._BOUND_R}|(?:{abbrev}){labels._BOUND_R}")
    assert right_only.search("USA 市場"), "left boundary is not load-bearing"

    left_only = _mutate(rf"{labels._BOUND_L}(?:{titles})s?|{labels._BOUND_L}(?:{abbrev})")
    assert left_only.search("Engineering"), "right boundary is not load-bearing"

    no_plural = _mutate(rf"{labels._BOUND_L}(?:{titles}){labels._BOUND_R}")
    assert not no_plural.search("Engineers"), "`s?` is not load-bearing"


def test_the_standards_named_examples_stay_covered() -> None:
    """The output standard names these three labels. Tidying the token list
    toward a clean semantic line would drop the first one."""
    for named in (
        "> **AppSec lens**: x",
        "> **FinOps Engineer lens**: x",
        "> **Chaos Engineering Practitioner lens**: x",
    ):
        assert labels.violations(named), f"the standard names this: {named!r}"


# ---------------------------------------------------------------- gate wiring


def test_selftest_passes() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--selftest"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_real_repository_passes() -> None:
    """Checked last. A guard only ever observed passing is not known to work."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
