# AGENTS.md

VMware ESXi → Amazon EC2 + Amazon FSx for NetApp ONTAP migration path
verification (NetApp Shift Toolkit / AWS Transform).

This file is read on every turn and cannot be made conditional, so it is an
index. The material lives in `docs/agent/`, tracked in git; `.kiro/` is
gitignored and holds only a loader that says when to read what.

- [docs/agent/README.md](docs/agent/README.md) — index of project conventions,
  output standards (naming, vendor neutrality, public-output safety, JA/EN
  parity), and quality gates.

## Run the gates

```bash
make install   # .venv を固定版で用意
make ci        # lint format-check test cfn-lint security headings role-labels drift
```

Never commit VMware or ONTAP credentials, personal names, AWS account IDs, or
support case numbers. Details in
[docs/agent/output-standards.md](docs/agent/output-standards.md).

## Architecture diagrams (draw.io)

Generate the `.drawio` XML directly with icons embedded as
`shape=image;image=data:image/svg+xml,<base64>`. The draw.io MCP tools and the built-in
`mxgraph.aws4.*` service shapes both produce a file whose icons vanish on export. Read
[docs/agent/diagrams.md](docs/agent/diagrams.md) before touching a diagram or its builder.
Rebuild with `make diagrams`, confirm with `make diagrams-check`, and look at the exported
PNG: a valid parse says nothing about the picture.
