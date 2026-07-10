# config/agent/

Agent-consumed config (DQ rules, executor prompts, IAM runner manifest, verification registry,
cost-reconciliation baselines). NOT bundled into any Lambda zip.

Placement and bundling rules are authoritative in `config/CLAUDE.md` (auto-loads when you edit this
tree). This README is a CD.23 portal projection; see `config/CLAUDE.md` for the three-zone layout
and the never-Lambda-bundled invariant.
