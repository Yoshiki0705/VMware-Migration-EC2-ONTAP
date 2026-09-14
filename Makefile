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

.PHONY: role-labels
# ネットワーク不要なので ci に入れる。語の禁止ではなく「職種トークンとレンズ語の同居」を
# 見る。語だけを禁じると「セキュリティの観点から」に発火し、allow を付けられて死ぬ。
role-labels: ## ラベルが職種名を名乗っていないか（所見ではなくラベルだけの問題）
	$(PYTHON) tools/check_role_labels.py --selftest >/dev/null
	$(PYTHON) tools/check_role_labels.py

.PHONY: repo-names
# ネットワークが必要なので ci には入れない。週次の repo-names.yml が呼ぶ。
# 未認証の API は 1 時間 60 回なので、手元で繰り返すなら GITHUB_TOKEN を渡す:
#   GITHUB_TOKEN=$$(gh auth token) make repo-names
repo-names: ## 散文中のリポジトリ名がいまの名前か（旧名は GitHub が解決し続けるので他に出ない）
	$(PYTHON) tools/check_repo_names.py --selftest >/dev/null
	$(PYTHON) tools/check_repo_names.py

# サポートケースの台帳は生成物。**AWS 認証が必要で、生成先は .private/ なので CI では走らない。**
# `--check` は差分があれば exit 1 を返すので、状態が動いたかどうかだけを見たいときに使う。
.PHONY: support-status support-status-check
support-status: ## サポートケースの状態と応答ログを Support API から再生成（ローカル専用）
	$(PYTHON) scripts/sync_support_case_status.py

support-status-check: ## 再生成しても現在のファイルと一致するか（差分があれば exit 1）
	$(PYTHON) scripts/sync_support_case_status.py --check

# `.private/` は gitignore なので CI には無い。**公開面の下書きを含めるのはローカルだけ**で、
# 既定に入れると「ローカルでは落ちるが CI では緑」になる。公開前の監査で 1 度通す。
.PHONY: repo-names-private
repo-names-private: ## 下書き・内部ノートのリポジトリ名まで含める（ローカル専用・ネットワーク必要）
	$(PYTHON) tools/check_repo_names.py --selftest >/dev/null
	$(PYTHON) tools/check_repo_names.py --include-private

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
.PHONY: draft-parity
# .private は gitignore なので CI の JA/EN 検査が届かない。**同じ漏れを 3 回踏んだので
# 手作業の数え上げを検査にした。** ドラフトが無いクローンではスキップする。
draft-parity: ## ブログ下書きの JA/EN が構造的に一致しているか（ローカル専用）
	$(PYTHON) tools/check_draft_parity.py --selftest >/dev/null
	$(PYTHON) tools/check_draft_parity.py

.PHONY: outgoing-probes
# 引用した他リポジトリの主張が言い換えられていないか。**姉妹側の incoming-probes は
# Adoption Playbook 1 本にしか繋がっていないので、こちらの保護はこちら側にしか無い。**
# チェックアウトが無ければスキップするが、スキップは合格ではない。
# `OUTGOING_PROBE_FLAGS=--strict` にすると、スキップと作業ツリーへのフォールバックを失敗として
# 扱う。**CI はこれを渡す。** ローカルではチェックアウトが無いこともあるが、CI で緑になった実行が
# 実は何も検査していない形は、ゲートが無いのと変わらない。
OUTGOING_PROBE_FLAGS ?=

outgoing-probes: ## 姉妹リポジトリから引用した主張が生きているか（チェックアウトが無ければスキップ）
	$(PYTHON) tools/check_outgoing_probes.py --selftest >/dev/null
	$(PYTHON) tools/check_outgoing_probes.py $(OUTGOING_PROBE_FLAGS)

.PHONY: incoming-probes
incoming-probes: ## 姉妹リポジトリがこちらから引用した文が、こちらの編集で消えていないか
	$(PYTHON) tools/check_incoming_probes.py --selftest >/dev/null
	$(PYTHON) tools/check_incoming_probes.py $(OUTGOING_PROBE_FLAGS)

.PHONY: diagrams
diagrams: ## 図を再生成し SVG / PNG を書き出す（AWS アイコンパッケージと draw.io が必要）
	$(PYTHON) tools/build_diagrams.py --write --export

.PHONY: diagrams-check
diagrams-check: ## committed の図が spec と一致するか（AWS アイコンパッケージが必要）
	$(PYTHON) tools/build_diagrams.py --check

.PHONY: drift
drift: agent-config context-budget diagram-assets diagram-fonts diagram-flow outgoing-probes draft-parity ## 逆戻り検出（設定の到達性 + 常時ロード予算 + 図の成果物 + ラベルの可読性と向き）

.PHONY: gates
# **どこでも走る集合**。~/.kiro を要求する agent-config、システムバイナリの shellcheck、
# ネットワークを要る repo-names は入らない。CI・pre-commit フック・共同作業者の手元の
# 3 か所がこの 1 つの定義を呼ぶ。
#
# ci.yml がこの一覧と一致していることは scripts/tests/test_ci_gate_parity.py が見る。
# 以前は Makefile のコメントが「diagram-fonts / diagram-flow は CI で常時走らせる」と
# 書いているのに ci.yml が drift を呼んでおらず、3 つの図の検査が一度も CI で走って
# いなかった。集合を 2 か所に書くと、片方だけが更新される。
gates: lint format-check test cfn-lint security headings role-labels context-budget diagram-assets diagram-fonts diagram-flow incoming-probes ## どこでも走る検査（CI とフックが呼ぶ）

.PHONY: ci
ci: gates agent-config ## CI が呼ぶ集約ターゲット（gates + ~/.kiro 依存の到達性検査）

.PHONY: all
all: ci ## ci の別名
