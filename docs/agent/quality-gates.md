# Quality gates

Every gate is a `make` target. CI calls those targets rather than invoking tools
directly, and the path lists live in Makefile variables, so a local run and a CI
run inspect the same tree with the same tool version.

```bash
make install    # .venv を作り requirements*.txt を固定版で導入
make tools      # 各ツールの解決先とバージョン（ローカルと CI の差を見る）
make gates      # どこでも走る検査（CI と .githooks/pre-commit が呼ぶ）
make ci         # gates + agent-config（~/.kiro に依存するため CI では走らない）
make drift      # 設定の到達性 + 常時ロードコンテキスト予算

# ネットワークが必要なので ci に入っていない。週次 workflow が呼ぶ
GITHUB_TOKEN=$(gh auth token) make repo-names
```

## Gate inventory

| Target | Tool | Scope variable |
|---|---|---|
| `lint`, `format-check` | ruff | `PY_PATHS` |
| `test` | pytest | `TEST_DIRS` |
| `cfn-lint` | cfn-lint | `TEMPLATE_GLOB` |
| `security` | bandit (`-ll`, Medium 以上) | `PY_PATHS` |
| `headings` | `tools/check_heading_style.py` (selftest, then scan) | `HEADING_CHECK`; walk scope is the script's `SKIP` set |
| `shellcheck` | shellcheck | `SHELL_PATHS` |
| `agent-config` | global `validate_agent_config.py` | steering / skills / hooks |
| `context-budget` | `scripts/check_agent_context_budget.py` | AGENTS.md, `.kiro/steering/` |
| `role-labels` | `tools/check_role_labels.py` (selftest, then scan) | headings and leading bold labels in `*.md`, **excluding code fences** |
| `repo-names` | `tools/check_repo_names.py` (selftest, then resolve) | every `*.md` outside the script's `SKIP` set, **including code fences** |

Those last two want opposite things from the same text, which is why neither can
share a fence-stripping helper. A fenced example of a forbidden label is a
quotation; a fenced clone URL is something a reader runs.

`shellcheck` is not part of `ci` because it is a system binary rather than a
pinned Python package; CI runs it as a separate job.

`repo-names` is not part of `ci` because it needs the network. Weekly
`.github/workflows/repo-names.yml` runs it and passes `github.token`, which
raises the API allowance from 60 requests an hour to 5,000. It exits 1 on a stale
name and **2 when some name could not be resolved at all**, so a rate limit or an
outage is not reported as a finding.

## Tool versions

`requirements.txt` holds what the scripts need at runtime. `requirements-dev.txt`
holds what the gates need. Both are exact-pinned. Widening either to a range
reintroduces the divergence described below.

## Pitfalls measured in this repository

| Pitfall | Root cause | Resolution |
|---|---|---|
| A `make` target named after an existing directory silently no-ops | make treats it as an up-to-date file target | All targets declared `.PHONY`; `scripts/tests/test_makefile_phony.py` fails the build on a new undeclared target and asserts `make -n security` emits a `bandit` line |
| CI reported a passing test gate with no tests | `pytest tests/ -v \|\| true` against a `tests/` directory that did not exist | `TEST_DIRS = scripts/tests`, no `\|\| true`; the directory now exists and is the only place tests live |
| Local and CI could disagree on lint results | CI ran `pip install ruff cfn-lint` unpinned while `requirements.txt` pinned `cfn-lint==1.52.0`; `ruff` was pinned nowhere | Both pinned in `requirements-dev.txt`; CI calls `make` targets |
| A gate list written in two places drifted | See the diagram-gate row below. The general form: any set named in both the Makefile and a workflow will be updated in one of them only | Sets live in Makefile variables or targets; callers name the target. `test_ci_gate_parity.py` and `test_makefile_phony.py` both exist to hold that |
| `.pre-commit-config.yaml` describes hooks that never ran | `pre-commit` is not installed locally; `core.hooksPath` points at `.githooks`, so only what is in that directory executes | Documented here. `.githooks/pre-commit` and `.githooks/pre-push` are the gates that actually run locally. Both live in the repository rather than in a global `hooksPath`, so they are visible to collaborators and cannot drift to one machine |
| A new Python directory escaping lint | `PY_PATHS` named only `scripts`, so `tools/` would have been unlinted and unscanned | `PY_PATHS = scripts tools`; adding a Python directory means adding it here |
| A local virtualenv on a different Python than CI | `.venv` was created with Python 3.14; CI pins 3.12 | Unresolved — recreate `.venv` on 3.12 with `make install` if a version-sensitive failure appears |
| gitleaks reported "no leaks found" while never reading a single document | `.gitleaks.toml` allowlisted `.*\.md$`, removing every Markdown file from the scan. Scanned volume was 207 KB against 950 KB of repository content | The blanket path entry is gone; narrow allowlists replace it. See the notes in `.gitleaks.toml` |
| The `internal-hostname` rule fired on every RFC 2606 example domain | `[\w.-]+\.(?:internal\|corp\|local)\b` matched the `.corp` inside `corp.example.com`, so the suffix did not have to end the hostname | Suffix anchored with `(?:$\|[^\w.-])`. Go RE2 has no lookahead, so the tail is spelled out |
| Three diagram gates never ran in CI | The Makefile placed `diagram-fonts` and `diagram-flow` in `drift` with a comment saying CI therefore runs them always. `ci.yml` never invoked `drift`; it invoked `context-budget` alone. The comment stayed true-looking because nothing compared the two files | `make gates` is the single definition of the portable set, invoked by CI and by `.githooks/pre-commit`. `scripts/tests/test_ci_gate_parity.py` fails when `ci.yml` stops matching it, and proves its own parsing against broken input |
| A failing gate was hidden by a pipe | `make all \| tail -4 && git commit` returns tail's status, so `&&` never sees the failure. Observed twice on a sibling project; a second occurrence read past the failure on screen. Both were caught only by CI — downstream of the mistake | `.githooks/pre-commit` runs `make gates` (about 4s). git reads the hook's own exit status, so no pipe upstream can hide it. `SKIP_GATE=1` skips deliberately. **It inspects the working tree, not the staged content**, so unstaged edits mean it validates something other than the commit |
| A role token matched inside a longer, unrelated word | Boundaries were put on the abbreviations only (`SA`, `CISO`, …) and left off the title words, so `Engineer` matched `Engineering`, `Architect` matched `Architecture` and `Architectural`, and `エンジニア` matched `エンジニアリング`. **Four false positives, one family** — fixing the case that was reported would have left the other three | Both sides bounded, with the class excluding digits and `_` (`[^A-Za-z]` treats `_` as a boundary, which is looser than `\b`). Plurals kept via `s?`, since `Engineers` are people and `Engineering` is a field. `test_check_role_labels.py` mutates the pattern: removing either boundary or the `s?` fails a test, so no guard is decorative |
| A role-name label survived two detectors | One matched `lens\|の視点\|perspective`, so `レンズ` and `観点` passed. Widening it to the words alone is worse: 観点 and 視点 are ordinary Japanese, so a rule firing on "セキュリティの観点から" collects allow markers and then guards nothing. The form was also missed — the instance here was a **heading**, not an inline callout | `tools/check_role_labels.py` requires a **role token and a lens word in the same label**, and treats only headings and leading bold runs as labels. 14 selftest cases plus tests in both directions |
| Four git operations create commits without invoking `pre-commit` | Measured on git 2.54.0 with a marker hook: `git commit` and `git commit --amend` run it; **`git rebase --continue`, `git merge --no-ff`, `git cherry-pick` and `git revert` do not.** A conflict resolved by hand during a rebase therefore produces commits that never saw a gate. `git merge` has `pre-merge-commit`, but rebase, cherry-pick and revert have no pre-commit equivalent, so covering them individually is not possible | `.githooks/pre-push` runs `make gates` as well. Push is the one chokepoint every path passes through. `pre-commit` stays for fast feedback. `SKIP_GATE=1` skips both. Verified against a local bare remote: blocked on a failing gate, pushed with the override, pushed when passing, and skipped for a branch deletion |
| A commit landed on the default branch | A branch was created, the session returned to `main` unnoticed, and the commit landed there. Nothing was pushed; recovery was a branch-pointer move. The only control was remembering to check, which fails precisely when attention is elsewhere | `.githooks/pre-commit` refuses to commit on `main`/`master` unless `ALLOW_MAIN_COMMIT=1`. Verified in a scratch repository: blocked on `main`, allowed with the override, allowed on a feature branch |
| A rename check was silent on the rename it was written for | The first version compared the final URL after following redirects. **GitHub resolves repository names case-insensitively and serves the requested casing with 200**, so a case-only rename never redirects and reads as current. This repository's own rename was case-only. The break test used one of the names that does redirect, so the gap did not surface | `tools/check_repo_names.py` asks the API for `full_name`. `scripts/tests/test_check_repo_names.py` parametrizes the break test over **both** rename families — case-only and slug — because firing on one member proves nothing about the rest |
| A first control test appeared to prove the scanner was broken | The planted value was `AKIAIOSFODNN7EXAMPLE`, which gitleaks' default config allowlists as a known placeholder | Control inputs must be values the rules actually reject. The working probe plants a private key block, an RFC 1918 address, an internal hostname, an account ID, an address, and a vCenter password, and asserts all six rules fire |

## Guard outcomes

Both guards distinguish three outcomes so a warning cannot be mistaken for a
pass:

| Outcome | `check_agent_context_budget.py` | Global irreversible-operations hook |
|---|---|---|
| block | exit 1: over the hard cap, an index target missing, or untracked | `command` action, exit 2 |
| ask | exit 0 with `warning:` lines: past the warn threshold | exit 2 with an approval instruction |
| allow | exit 0, silent | exit 0, silent |

A guard that has never been observed rejecting bad input is not known to work.
`scripts/tests/` exercises the rejection paths, not only the healthy ones.

## Secret scanning scope

`gitleaks` has two scan modes and they do not cover the same thing.

| Invocation | Covers | Used by |
|---|---|---|
| `gitleaks detect --no-git --source .` | The working tree only | Local checks, `.githooks/pre-commit` |
| `gitleaks detect` | Every commit reachable from HEAD | CI (`gitleaks-action` with `fetch-depth: 0`) |

A clean working tree therefore does not imply CI will pass. **History is permanent**:
a value removed from the tree is still reachable from the commits that introduced it,
and removing it from history needs a rewrite plus a force-push.

`.gitleaks.toml` carries a rule-scoped `commits` allowlist for one accepted historical
finding, a vendor support address committed before Markdown was in scope. The allowlist
is scoped to that rule and to those four commit SHAs, so a new occurrence still fails.
Verify both modes and the rejection path before trusting a clean result:

```bash
gitleaks detect --config .gitleaks.toml --no-git --source .   # tree
gitleaks detect --config .gitleaks.toml                       # history, as CI sees it
```
