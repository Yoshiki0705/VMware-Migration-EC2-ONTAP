# Agent-facing documentation

AGENTS.md is read on every turn and cannot be made conditional, so it holds an
index only. The material itself lives here, tracked in git so it is readable on
GitHub. `.kiro/` is gitignored in this repository (BLEA-style), which is why no
knowledge body may live there.

| Document | Read it when |
|---|---|
| [project-conventions.md](project-conventions.md) | Starting work: phases, directory layout, Phase 1 entry gate |
| [output-standards.md](output-standards.md) | Writing or reviewing any document, commit message, or PR |
| [quality-gates.md](quality-gates.md) | Running or changing a gate, or adding a dependency |
| [diagrams.md](diagrams.md) | Creating or regenerating an architecture diagram |

Global rules (naming, vendor neutrality, writing style, public-output safety)
come from user-level Kiro steering and apply to every repository. The documents
here cover only what is specific to this one.

Container data-store patterns (using FSx for ONTAP from ECS / EKS, including
AWS Transform containerization workloads) live in a separate repository,
[FSx-for-ONTAP-Container-Datastore-Patterns](https://github.com/Yoshiki0705/FSx-for-ONTAP-Container-Datastore-Patterns).
This repository covers the VMware → EC2 rehost migration path.
