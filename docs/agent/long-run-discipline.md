# Long-run discipline — repository connections

Three disciplines for long autonomous runs live in user-level Kiro global
steering (`ai-agent-workflow`'s Parallel-by-default and Auditor Sub-Agent
sections, and `benchmark-and-evidence-standards`). That is the base and applies
to every repository. This file does not copy it. It records only what is
specific to this repository: where decision records go, which evidence vocabulary
to use, and the recurring task types found here.

## Decision records — where and what

A multi-stage task (adding a migration-path verification, changing a template,
an IaC change) keeps a decision record alongside its implementation notes, with
three sections kept together in one file — not split across files, and not a new
kind of container each time:

```markdown
## Decisions
- <what was decided>: <why. basis: measurement / documentation / assumption>

## Rejected alternatives
- <option rejected>: <why. could it return if the situation changes?>

## Assumptions
- <taken on without verifying>: <what breaks if it is wrong>
```

Location follows this repository's existing habit, not the Hub's `.agents/tasks/`:

- Agent material is tracked under `docs/agent/` here, and `.kiro/` is gitignored.
- A decision record carries process metadata (rejected options, unverified
  assumptions, evidence basis), which `output-standards.md` keeps out of
  published docs. So the per-task record is **not** published.
- Put it at `.private/tasks/<task>/impl-note.md` (gitignored). Add a row to the
  `.private/README.md` index when the task starts, and move it to the archive
  table when the task closes — the same lifecycle the index already uses.
- If a task already has a record file under a different name, append the three
  sections to it rather than adding a new name.

## Evidence tier vocabulary

When the work involves verification, tag each `Decisions` basis with the words
this repository already uses. Do not introduce new ones. Two documents define
them: the status legend in [../en/netapp-questions.md](../en/netapp-questions.md)
(✅ Confirmed, 🔬 Measured, 🔶 Partial, ⬜ Unanswered) and the tag table in
[../en/atx-fsxn-ga-verification.md](../en/atx-fsxn-ga-verification.md)
(`[Measured]`, `[Documented]`, `[Unverified]`).
| Word | Meaning | Use in the basis field |
|---|---|---|
| 🔬 Measured / `[Measured]` | Established by hands-on verification in our own environment | basis: measurement |
| ✅ Confirmed | Answered from public blog / vendor documentation | basis: documentation |
| `[Documented]` | Stated in AWS / NetApp documentation | basis: documentation |
| ⬜ Unanswered / `[Unverified]` | Not verified; an assumption or open point | basis: assumption |
A single-run number is `[Unverified]` until its run-to-run variance is known (see
the measurement section below).

## Auditor signals

Call `semantic_reviewer` (re-examine the judgement) or `context-gatherer`
(confirm the assumptions match the implementation) before continuing, and hand
over the decision record and the change diff, on any of:

- the same approach has failed twice,
- the same file has been re-edited three or more times,
- the same error message recurs in a multi-stage task.

This repository has no evidence-ledger, UNV inventory, or ADR to carry the audit,
so use those two sub-agents directly — do not create a new mechanism and do not
add an automatic hook. Point the auditor at the judgement, not at reinforcing it:
which bases are assumptions, which rejected alternative should return now, which
unverified assumption would waste the work if it is wrong.

The pre-publish review just before committing a public document belongs to the
persona review board, not to the auditor. Keep them separate.

## Measure variance before claiming an effect

Before claiming an effect from a change to any performance, throughput, latency,
or cost number, first measure the run-to-run variance of the **unchanged**
configuration. If the change's delta is inside that variance, it is noise, not an
effect: say so, or raise the repetition count until the delta clears the variance.
A one-run-each "A is faster than B" gets the same treatment — it is `Unverified`
until variance is known.

The single-run migration timings already in the docs (for example the roughly
1 hour 49 minute Shift Toolkit total) are labelled single observations, not
general estimates. Keep that framing; do not promote a single run to a comparison.

## Recurring task types — checklists

Grow one item at a time. A second failure of the same kind is the signal that an
item is missing. These are this repository's task types; the base disciplines
above apply to each.

### Adding a migration-path verification (Phase 2x)

- [ ] Status word chosen for each new claim (🔬 Measured / ✅ Confirmed / `[Documented]` / `[Unverified]`)
- [ ] Single-run timings labelled as single observations, not estimates
- [ ] JA and EN updated in the same commit, matching section structure and count
- [ ] No VMware/ONTAP credentials, account IDs, or support case numbers in tracked files
- [ ] `.private/tasks/<task>/impl-note.md` carries the three decision sections

### Changing a CloudFormation template

- [ ] `make cfn-lint` passes; the template is inside `TEMPLATE_GLOB`
- [ ] `params/*.example.json` updated when a parameter shape changed
- [ ] Reuse of existing resources checked (do not recreate what the stack already makes)

### Changing or adding a gate

- [ ] Declared `.PHONY`; `make -n <target>` shows the tool actually runs
- [ ] The gate is proven to reject bad input (a selftest or a planted failure), not only to pass
- [ ] Added to `make gates` if it should run in CI and the local pre-commit hook
- [ ] Glob/directory-walk gates have a coverage test deriving expected targets from disk
