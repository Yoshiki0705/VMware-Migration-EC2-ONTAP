# Quality gates for vmware-migration-ec2-ontap.
#
# Two invariants this file exists to hold:
#
# 1. Every target is declared in .PHONY. Targets named after a directory that
#    exists on disk (docs, scripts, templates, security) are otherwise treated
#    by make as up-to-date files, so make prints "up to date" and never runs the
#    recipe. The gate reads as passing while having executed nothing.
#    scripts/tests/test_makefile_phony.py fails the build if a target is added
#    without being declared.
#
# 2. Path lists live in variables here and CI calls these targets, so local and
#    CI cannot end up inspecting different trees.
#
# Tools resolve from .venv when it exists, otherwise from PATH. Versions are
# pinned in requirements-dev.txt.

VENV      := .venv
VENV_BIN  := $(VENV)/bin
tool       = $(if $(wildcard $(VENV_BIN)/$(1)),$(VENV_BIN)/$(1),$(1))

PYTHON    := $(call tool,python)
PIP       := $(call tool,pip)
RUFF      := $(call tool,ruff)
PYTEST    := $(call tool,pytest)
CFN_LINT  := $(call tool,cfn-lint)
BANDIT    := $(call tool,bandit)

# Single source of truth for what each gate inspects.
PY_PATHS      := scripts tools
TEST_DIRS     := scripts/tests
TEMPLATE_GLOB := templates/*.yaml
SHELL_PATHS   := scripts
DOC_GLOBS     := docs/**/*.md README.md README.en.md
AGENTS_FILE   := AGENTS.md
# 見出し検査の走査範囲は検出器の SKIP 集合が単一の定義。ここでは呼び先だけ持つ。
HEADING_CHECK := tools/check_heading_style.py

.DEFAULT_GOAL := help

.PHONY: help
help: ## このファイルのターゲット一覧
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## .venv を作り requirements を固定版で導入
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

.PHONY: tools
tools: ## 各ツールの解決先とバージョンを表示（ローカルと CI の差を見るため）
	@for t in ruff cfn-lint pytest bandit; do \
		resolved=$$( [ -x "$(VENV_BIN)/$$t" ] && echo "$(VENV_BIN)/$$t" || command -v $$t || echo "(not found)" ); \
		printf '%-10s %-24s ' "$$t" "$$resolved"; \
		[ -x "$$resolved" ] && "$$resolved" --version 2>&1 | head -1 || echo ""; \
	done

.PHONY: lint
lint: ## ruff check
	$(RUFF) check $(PY_PATHS)

.PHONY: format-check
format-check: ## ruff format --check
	$(RUFF) format --check $(PY_PATHS)

.PHONY: format
format: ## ruff format（書き換える）
	$(RUFF) format $(PY_PATHS)

.PHONY: test
test: ## pytest（TEST_DIRS を明示。|| true で結果を捨てない）
	$(PYTEST) $(TEST_DIRS) -v --tb=short

.PHONY: cfn-lint
cfn-lint: ## CloudFormation テンプレートの lint
	$(CFN_LINT) $(TEMPLATE_GLOB)

.PHONY: security
security: ## bandit（Medium 以上でブロック）
	$(BANDIT) -r $(PY_PATHS) -ll

.PHONY: shellcheck
shellcheck: ## shellcheck（未導入ならスキップ理由を出して失敗させる）
	@command -v shellcheck >/dev/null || { echo "shellcheck が見つかりません。brew install shellcheck"; exit 1; }
	shellcheck --severity=warning $(SHELL_PATHS)/*.sh

.PHONY: headings
headings: ## 日本語の節見出しが体言止めか（本検査の前に自己テストを走らせる）
	@$(PYTHON) $(HEADING_CHECK) --selftest >/dev/null
	$(PYTHON) $(HEADING_CHECK)

.PHONY: repo-names
# ネットワークが必要なので ci には入れない。週次の repo-names.yml が呼ぶ。
# 未認証の API は 1 時間 60 回なので、手元で繰り返すなら GITHUB_TOKEN を渡す:
#   GITHUB_TOKEN=$$(gh auth token) make repo-names
repo-names: ## 散文中のリポジトリ名がいまの名前か（旧名は GitHub が解決し続けるので他に出ない）
	$(PYTHON) tools/check_repo_names.py --selftest >/dev/null
	$(PYTHON) tools/check_repo_names.py

.PHONY: agent-config
agent-config: ## steering / skills / hooks の到達性（グローバル検証器）
	$(PYTHON) $${KIRO_HOME:-$$HOME/.kiro}/hooks/scripts/validate_agent_config.py

.PHONY: context-budget
context-budget: ## 常時ロードコンテキストの上限とローダーの薄さ
	$(PYTHON) scripts/check_agent_context_budget.py

.PHONY: diagram-assets
diagram-assets: ## 図の成果物の一貫性（アイコン非同梱・欠落・EN への日本語残留）
	$(PYTHON) scripts/check_diagram_assets.py

.PHONY: diagram-fonts
# diagram-assets と違い、AWS アイコンパッケージも draw.io も要らない。committed の
# .drawio と .svg だけを読むので drift に入れて CI で常時走らせる。
diagram-fonts: ## 図のラベルが可読性の下限を満たすか（実効サイズと fontSize の 2 つ）
	$(PYTHON) tools/check_diagram_fonts.py --selftest >/dev/null
	$(PYTHON) tools/check_diagram_fonts.py

.PHONY: diagram-flow
# 同じ理由で drift に入れる。向きとラベル位置はソースを読んでも分からず、書き出した画像に
# しか現れない。PR #22 で 3 図を直したが、そのときは検査器がなかったので次に崩れても気づけない。
diagram-flow: ## 図が右向き・下向きだけで読めるか（ラベルはアイコンの下、枠のタイトルは角）
	$(PYTHON) tools/check_diagram_flow.py --selftest >/dev/null
	$(PYTHON) tools/check_diagram_flow.py
.PHONY: diagrams
diagrams: ## 図を再生成し SVG / PNG を書き出す（AWS アイコンパッケージと draw.io が必要）
	$(PYTHON) tools/build_diagrams.py --write --export

.PHONY: diagrams-check
diagrams-check: ## committed の図が spec と一致するか（AWS アイコンパッケージが必要）
	$(PYTHON) tools/build_diagrams.py --check

.PHONY: drift
drift: agent-config context-budget diagram-assets diagram-fonts diagram-flow ## 逆戻り検出（設定の到達性 + 常時ロード予算 + 図の成果物 + ラベルの可読性と向き）

.PHONY: ci
ci: lint format-check test cfn-lint security headings drift ## CI が呼ぶ集約ターゲット

.PHONY: all
all: ci ## ci の別名
