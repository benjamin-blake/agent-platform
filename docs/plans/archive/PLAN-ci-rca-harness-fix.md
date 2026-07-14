# Plan

## Intent
Restore the ci-rca merge-gate harness so the Decision 73 forward-fix model receives the failure signals it requires. Without a working ci-rca, main-branch failures slip through as silently missed signals instead of visible hard-blocks on the planning queue and PR auto-merge.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/ci-rca-harness-fix

## Phase
Phase Platform (parallel automation infrastructure). Specifically: merge-gate harness reliability for the Decision 73 forward-fix CI model. Not on a Product Phase track.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/workflows/ci-rca.yml` | Modify | (a) Add `sudo` + `--omit=dev --omit=optional` + pinned version `@2.1.148` to `npm install -g`; (b) add `workflow_dispatch: inputs: run_id` trigger so the agent can be re-run against past failures without pushing fake CI failures; (c) source `RUN_ID` from `workflow_run.id OR inputs.run_id`; (d) insert inline `TODO(bedrock)` comment above the Install step. |
| `terraform/ec2_runner.tf` | Modify | Add `npm install -g @anthropic-ai/claude-code@2.1.148 --omit=dev --omit=optional && npm cache clean --force` to `user_data`, after the existing `apt-get install -y nodejs` line. Pre-bakes the CLI into any future runner recreation. |
| `.github/workflows/diagnostic-disk.yml` | Delete | One-shot diagnostic completed. Disk data collected (3.6GB free, 82% used, CLI install footprint 167KB confirmed via `npm view`). Delete to keep workflow inventory clean. |
| `docs/DECISIONS.md` | Modify | Add Decision 74 — pre-install ci-rca CLI in runner user_data + add `workflow_dispatch` escape hatch. Cites the EACCES failure of run 26287172232 as evidence. |

## Bundled Recommendations
None. Two follow-up recs will be filed by ci-rca itself OR by the planner after verification proves the harness works (cleanup-actions-runner-workspace; restore-runner-swap).

## Infrastructure Dependencies

| Resource | Change Type | Timing | Replacement Risk |
|----------|-------------|--------|------------------|
| `aws_instance.github_runner` (terraform/ec2_runner.tf) | `user_data` attribute update | Pre-merge `terraform apply` (Decision 68 + Terraform CLAUDE.md: present plan to human first) | LOW. AWS provider v4+ defaults `user_data_replace_on_change = false`. Apply updates the stored attribute only; the running instance does not re-execute user_data. The CLI is NOT installed on the existing runner by this apply -- only on future recreations. |
| Existing runner instance | NO direct change | NOT triggered | The existing runner self-heals via the workflow YAML change (sudo npm install runs on first ci-rca dispatch after merge). |

**Apply ordering:** No IAM change in this plan, so terraform-before-Lambda ordering does not apply. Terraform apply must precede the ci-rca dispatch verification (Step 8) so the user_data state matches what's documented in Decision 74 by the time the rec is filed.

## Acceptance Criteria
- [ ] ci-rca workflow `Install Claude Code CLI` step completes successfully on the existing self-hosted runner (sudo path).
- [ ] ci-rca workflow `Run ci-rca agent` step produces JSON output containing a `rec-XXX` ID for CI run `26286390667`.
- [ ] The filed recommendation has `source: "ci_rca"`, `priority: "critical"`, non-empty `file`, and references the SLOC limit violation in `scripts/product_roadmap.py`.
- [ ] Subsequent `session_preflight` shows `ci_rca_recs` length >= 1 and `ci_rca_liveness_alert` is null (or pointing to a different run_url).
- [ ] `terraform apply` updated `aws_instance.github_runner.user_data` attribute without forcing instance replacement (verified by reading apply output).
- [ ] Decision 74 entry added to `docs/DECISIONS.md` with citation to failed run `26287172232`.
- [ ] `.github/workflows/diagnostic-disk.yml` deleted.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Validate ci-rca.yml is parseable YAML and has both triggers | `bin/venv-python -c "import yaml; w = yaml.safe_load(open('.github/workflows/ci-rca.yml')); assert 'workflow_run' in w['on']; assert 'workflow_dispatch' in w['on']; assert w['on']['workflow_dispatch']['inputs']['run_id']['required'] is True; print('OK')"` | Prints `OK` | YAML invalid or schema wrong -- restructure |
| 2 | [pre-deploy] | Confirm Bedrock TODO is placed above the Install step | `bin/venv-python -c "import re; t = open('.github/workflows/ci-rca.yml').read(); m = re.search(r'TODO\(bedrock\)[\s\S]*?Install Claude Code CLI', t); assert m, 'TODO(bedrock) not directly above Install step'; print('OK')"` | Prints `OK` | Move comment so it textually precedes the install step |
| 3 | [pre-deploy] | Confirm npm install line uses sudo + pinned version + lean flags | `grep -E "sudo npm install -g @anthropic-ai/claude-code@2\\.1\\.148.*--omit=dev.*--omit=optional" .github/workflows/ci-rca.yml` | One match printed | Restore the flags / pin |
| 4 | [pre-deploy] | Confirm RUN_ID is sourced from either trigger | `grep -E 'RUN_ID="\$\{\{ github\.event\.workflow_run\.id \|\| github\.event\.inputs\.run_id \}\}"' .github/workflows/ci-rca.yml` | One match | Fix RUN_ID expression |
| 5 | [pre-deploy] | Confirm diagnostic-disk.yml is deleted | `bin/venv-python -c "import pathlib; assert not pathlib.Path('.github/workflows/diagnostic-disk.yml').exists(); print('OK')"` | Prints `OK` | `git rm` the file |
| 6 | [pre-deploy] | Confirm Decision 74 is added and cites failed run | `grep -E "^## Decision 74:" docs/DECISIONS.md && grep -E "26287172232" docs/DECISIONS.md` | Both grep statements return a match | Add decision entry with run ID citation |
| 7 | [pre-deploy] | terraform plan -- present to human; abort if anything beyond `aws_instance.github_runner.user_data` changes | `cd terraform && terraform plan -no-color -out=ci-rca-fix.tfplan` | Plan shows exactly one in-place update on `aws_instance.github_runner`; only `user_data` attribute differs; no replacement triggered | Investigate any unexpected resource diff; revise scope if necessary |
| 8 | [post-deploy] | Human approves the plan; apply | `cd terraform && terraform apply ci-rca-fix.tfplan` | Apply succeeds; no resource replacement; ~1s execution | If apply errors or forces replacement, run `terraform plan` again and inspect drift |
| 9 | [post-deploy] | Trigger ci-rca against the failing CI run via the new workflow_dispatch | `gh workflow run ci-rca.yml --ref agent/ci-rca-harness-fix -f run_id=26286390667` | Returns "Workflow run dispatched" (or empty + exit 0) | If "workflow not found": wait 30s for GitHub indexing, retry; if persistent, push a no-op commit to re-index |
| 10 | [post-deploy] | Identify the new run ID | `gh run list --workflow=ci-rca.yml --branch agent/ci-rca-harness-fix --limit 1 --json databaseId,status --jq '.[0].databaseId'` | Numeric run ID | If empty, wait 10s and retry |
| 11 | [post-deploy] | Watch run to completion (timeout-bounded to the workflow's 20min limit) | `gh run watch <run-id> --exit-status --interval 15` | Exit 0; all three steps (`Checkout at failing commit`, `Install Claude Code CLI`, `Run ci-rca agent`) green | If Install fails: check sudo availability on runner; if Run fails: check Claude API auth / OAuth token expiry |
| 12 | [post-deploy] | Confirm the agent JSON output contains a rec ID and source=ci_rca | `gh run view <run-id> --log \| grep -oE '"rec-[0-9]+"' \| head -1 && gh run view <run-id> --log \| grep -oE '"source":\s*"ci_rca"' \| head -1` | Both greps print one match each | Re-read the agent output and follow the methodology in `.claude/agents/scheduled/ci-rca.md` |
| 13 | [post-deploy] | Sync ops cache and confirm the rec is queryable | `bin/venv-python -m scripts.ops_data_portal sync 2>&1 \| tail -3 && bin/venv-python -c "import json,pathlib; recs=[json.loads(l) for l in pathlib.Path('logs/.recommendations-log.jsonl').read_text().splitlines() if l.strip()]; ci=[r for r in recs if r.get('source')=='ci_rca' and r.get('status')=='open']; print(f'open ci_rca recs: {len(ci)}'); assert ci, 'no open ci_rca recs found'; print('latest:', ci[-1]['id'], ci[-1]['title'][:80])"` | "open ci_rca recs: >=1" + the latest rec is printed | If 0 open ci_rca recs: re-trigger ci-rca, verify the file_rec call succeeded in the run output |
| 14 | [post-deploy] | Confirm `ci_rca_liveness_alert` clears (or moves to a different run_url) and `ci_rca_recs` is populated | `bin/venv-python -m scripts.session_preflight 1>/dev/null 2>&1 && bin/venv-python -c "import json; r = json.load(open('logs/.preflight-report.json')); print('ci_rca_recs:', len(r.get('ci_rca_recs',[]))); print('liveness_alert:', r.get('ci_rca_liveness_alert'))"` | `ci_rca_recs` >= 1; `liveness_alert` either null or its `run_url` is NOT `https://github.com/.../actions/runs/26286390667` | If still alerting on 26286390667: the rec lookup may be filtering on commit SHA; review session_preflight ci-rca correlation logic |
| 15 | [post-deploy] | Spot-check: run a second ci-rca dispatch with the same run_id and confirm idempotency (no duplicate rec) | `gh workflow run ci-rca.yml --ref agent/ci-rca-harness-fix -f run_id=26286390667 && sleep 15 && gh run list --workflow=ci-rca.yml --limit 1 --json databaseId --jq '.[0].databaseId' \| xargs -I{} gh run watch {} --exit-status --interval 15` followed by `bin/venv-python -m scripts.ops_data_portal sync && bin/venv-python -c "import json,pathlib; recs=[json.loads(l) for l in pathlib.Path('logs/.recommendations-log.jsonl').read_text().splitlines() if l.strip()]; ci_for_run=[r for r in recs if r.get('source')=='ci_rca' and '26286390667' in (r.get('context','')+r.get('title',''))]; print(f'recs for run 26286390667: {len(ci_for_run)}')"` | Two dispatches but only one open rec referencing run `26286390667` (or, if the agent files a duplicate, the count is 2 and this is logged as a known gap) | If duplicate-filing happens: document as known gap; this is a separate hardening rec (`ci-rca-idempotency`) not blocking this plan |

## Constraints
- Plan Type is IMPLEMENTATION because the STRATEGIC classification is suspended under AGENTS.md Temporary Operational Constraints (Decision 67 freeze active). The heuristic (>5 files or >8 steps) is informational only during freeze. This plan has 4 scope files (well under 5) and 15 verification steps, but the steps are all single-file or single-resource operations -- no decomposition warranted.
- No rescue agents or workaround loops (Decision 55). If verification step 11 fails (ci-rca run errors), the appropriate response is to file a separate rec and pause the plan, not to bypass the gate.
- Terraform apply must precede ci-rca dispatch verification (Step 8 before Step 9). User_data attribute consistency in state is required even though it does not affect the running runner.
- The existing runner is the production runner; do NOT taint or recreate it as part of this plan. The plan deliberately exercises the workflow's self-install path on the existing runner, not the user_data path.
- Pinned version `@2.1.148` is the current npm registry version as of 2026-05-22. Future plans may bump.
- No port 22 opening, no IAM changes, no EC2 Instance Connect Endpoint required. Verification is entirely via GitHub API + AWS Athena (read-only).

## Context
- **Triggering incident**: CI run `26286390667` on `main` failed at 2026-05-22T11:57Z (SLOC limit violation, `scripts/product_roadmap.py` at 631 SLOC). ci-rca auto-triggered at 12:15Z (run `26287172232`) and crashed at the `Install Claude Code CLI` step with `npm error code EACCES ... mkdir '/usr/lib/node_modules/@anthropic-ai'`. A second ci-rca run earlier (`26284914206`) failed identically. No rec was filed; the Decision 73 forward-fix model received no failure signal.
- **Liveness alert state at planning time**: `ci_rca_liveness_alert` is firing (69.6 minutes elapsed, run_url `26286390667`). This plan IS the triage per the planning skill's HARD ALERT condition.
- **Disk inspection (diagnostic run `26291745718`)**: root volume 20G total, 16G used, **3.6G free (82% used)**. The whale is `/home/ubuntu/actions-runner` at 8.8G (workspace + tool cache accumulation across CI runs). Claude Code CLI install footprint via `npm view @anthropic-ai/claude-code dist.unpackedSize`: 136KB unpacked, 167KB total with no dependencies (verified by `npm install` to a temp dir). Disk concern is real but **unrelated to ci-rca**; the 167KB install is rounding error.
- **Decision 73 dependency**: this plan is corrective infrastructure for Decision 73 (Two-Tier Diff-Aware CI with Forward-Fix and Scheduled Promotion Train). Section 4 of D73 states "While an open ci-rca rec exists, `/plan` cannot scope unrelated work" -- but the inverse failure mode (no rec because the harness crashed) is not in D73's threat model. This plan adds the missing harness-reliability assumption.
- **Decision 72 dependency**: D72 (RCA-as-Plan-Source) introduced the ci-rca agent. This plan does not modify D72; it hardens its harness against EACCES and adds the dispatch escape hatch missing from the original implementation.
- **Self-hosted runner context (Decision 68)**: the runner runs as the `ubuntu` user. Ubuntu cloud AMIs configure `/etc/sudoers.d/90-cloud-init-users` with passwordless sudo for `ubuntu`, so `sudo npm install -g` is expected to succeed without modification to the runner. The verification in step 11 confirms this empirically.
- **Bedrock comment placement**: above the `Install Claude Code CLI` step in ci-rca.yml. The comment captures the broader migration plan -- both the install step and the `claude -p` invocation below would be replaced by a Python entrypoint using boto3 + bedrock-runtime via the runner's IAM role. Not in scope for this plan; out-of-scope per "we should hopefully be off the self-hosted EC2 within 90 days and back onto github" (user input, this session).
- **Token rotation deferred**: `CLAUDE_CODE_OAUTH_TOKEN` expires every ~90 days. Out of scope per user (90-day migration window to GitHub-hosted runners makes rotation unlikely to bite).
- **Known follow-up recommendations** (file after verification passes, not as part of this plan):
  - `cleanup-actions-runner-workspace` (HIGH) -- 8.8GB workspace bloat in `/home/ubuntu/actions-runner`; needs reclamation strategy.
  - `restore-runner-swap` (MEDIUM) -- user_data created `/swapfile` with fstab entry but `free -h` shows `Swap: 0B`; swapon not persisting across reboots.
  - `ci-rca-bedrock-migration` (LOW) -- migrate ci-rca to direct Bedrock invocation via Python harness; eliminates Claude Code CLI dependency and OAuth token rotation. Track until 90-day GitHub-hosted migration lands.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (we are on `agent/ci-rca-harness-fix`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (specifically Decisions 67, 68, 72, 73)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] Diagnostic data captured and inline-cited in Context (run 26291745718)
- [ ] Triggering CI run + failed ci-rca run IDs captured in Context (26286390667, 26287172232)

## Ordered Execution Steps
1. **Modify `.github/workflows/ci-rca.yml`**:
   - Add to `on:` block: `workflow_dispatch: { inputs: { run_id: { description: 'GitHub Actions run ID of the failed CI run to diagnose', required: true, type: string } } }`.
   - Replace the `Install Claude Code CLI` step's `npm install -g @anthropic-ai/claude-code` with `sudo npm install -g @anthropic-ai/claude-code@2.1.148 --omit=dev --omit=optional && sudo npm cache clean --force` (preserve the `if ! command -v claude` guard).
   - Replace `RUN_ID="${{ github.event.workflow_run.id }}"` with `RUN_ID="${{ github.event.workflow_run.id || github.event.inputs.run_id }}"`.
   - Insert above the `Install Claude Code CLI` step (as `# TODO(bedrock): ...` comment block) the multi-line Bedrock migration note approved during planning (text in the workflow file).
2. **Modify `terraform/ec2_runner.tf`**:
   - In the `user_data = <<EOF` heredoc, immediately after `apt-get install -y nodejs`, add: `npm install -g @anthropic-ai/claude-code@2.1.148 --omit=dev --omit=optional` and `npm cache clean --force`. user_data runs as root so no sudo needed.
3. **Delete `.github/workflows/diagnostic-disk.yml`**: `git rm .github/workflows/diagnostic-disk.yml`.
4. **Modify `docs/DECISIONS.md`**: Add Decision 74 entry at the top of the open-decisions list (above Decision 73). Cite failed run `26287172232`, reference Decision 72 (RCA-as-Plan-Source) and Decision 73 (forward-fix), document the `workflow_dispatch` escape hatch, and state the pre-install rationale.
5. **Commit** the four file changes with message `feat(ci-rca-harness-fix): pre-install Claude Code CLI + workflow_dispatch trigger + Decision 74`.
6. **Execute Verification Plan** -- run each step 1-15. Loop until pass. Steps 1-7 are pre-deploy and pre-merge. Step 7 (terraform plan) requires human approval of the plan output before step 8 (terraform apply). If V3 fails unrecoverably (step 11 or 12 cannot succeed after one root-cause investigation), stop and analyse per Decision 55 -- file a separate rec, do not patch around the failure.
7. **Open the PR** with title `fix(ci-rca): unbreak harness via pre-install + workflow_dispatch (Decision 74)`. Body must reference: original CI failure `26286390667`, failed ci-rca `26287172232`, the rec filed by ci-rca during step 13, and the Decision 74 link.
8. **Report**: what was implemented, verification results (paste the steps 11-14 command outputs), the rec ID filed by ci-rca, and the open follow-up recs identified during execution.
