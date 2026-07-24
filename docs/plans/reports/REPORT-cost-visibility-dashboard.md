# REPORT: Private variable-cost visibility dashboard (scoping)

> Scoping / spike note for platform tier item **T2.51**. Not an implementation. Captures the
> cost-proportion analysis, the architecture, and the timing rationale behind placing the
> capability on the roadmap as `deferred_post_mvp`. The roadmap entry (T2.51) is the canonical
> forward intent; this report is the design rationale it points back to.

## 1. Scope decision

This scopes visibility for **variable operational vendor spend only**:

- **In scope:** AWS (all services), the LLM inference APIs (DeepSeek Tier 1, Anthropic-direct
  Tier 2), and Neon (the DuckLake catalog).
- **Out of scope (deliberately):** the Claude Code Max subscription. It is a fixed line the owner
  tracks out-of-band, and excluding it is *more* future-proof, not less: as the platform shifts
  from the subscription/OAuth model to metered API rates, agent-inference spend becomes a metered
  Anthropic/DeepSeek line that a variable-spend tracker already covers. Nothing is lost long-term.
- **Consequence:** every in-scope line is billed in **USD**, so there is no currency-conversion
  layer to build. (Had the GBP subscription stayed in scope, a GBP reporting currency + fixed-FX
  convention would have been required; dropping it removes that entirely.)

## 2. The proportions (the actual question worth answering now)

The owner's real interest was the *shape* of spend, not the absolute figures (which are small
today). Using the platform's own `cost_projection` envelope in `docs/ROADMAP-PLATFORM.yaml`
(order-of-magnitude, list-price/projection figures - not measured invoices):

| Slice | Today (variable) | Grows with | Long-run |
|---|---|---|---|
| AWS operational (CloudWatch logs, Secrets Manager, Athena, DynamoDB, small S3) | dominant share of a small bill | flat-ish until data volume climbs | steady |
| **S3 storage** | `<$1` today | **data volume** | **~$800-1500/mo at the 100TB target (~85% of the projected bill)** |
| **LLM inference** (DeepSeek + Anthropic escape-hatch) | a few dollars | **agent/executor activity** | `$15-80+/mo` as the executor unfreezes / OAuth->API |
| Neon (catalog) | small, newly paid (post free-tier breach, Decision 88) | egress / query patterns | small if invariants held |

**The insight:** the cost structure has two future "whales" on different axes -
**inference (activity-driven, near-term)** and **storage (data-driven, long-term)** - and
everything else stays in the noise. A cost view is worth building to make *those two* legible over
time; it is not worth building to itemise today's flat spread of single-digit-dollar lines. This
is precisely why investigating now (when the numbers are cheap) is sensible, and why *building*
now is premature.

### What is easy to forget (the "what am I missing" answer)

- **Anthropic API direct** is a distinct line from the subscription. The Tier-2 escape hatch is
  funded by the Max programmatic-pool credit (part of the *excluded* subscription); the actual
  *variable* Anthropic spend this dashboard would track is the **deferred org-billed Anthropic API
  key** (CD.28's cost-monitoring follow-on), which bills at API rates. The reconciliation baseline
  (`anthropic_pool_size_usd: 100.0`, "Max x5") looks stale against a Max x20 subscription and
  should be re-grounded by the owner when this is built. The dashboard's pulls also feed CD.28's
  `cost_projection` reevaluation triggers (DeepSeek pricing >5x; pool >70% over 30d).
- **Neon is no longer free.** It breached the 5 GB/month free tier on 2026-06-15 and forced a
  paid upgrade (Decision 88 / `PLAN-neon-egress-reduction`). The `cost_projection` still records
  it as `$0 free tier` - stale.
- **Cross-cloud egress** (AWS <-> Neon) is the specific thing Decision 88 polices.
- **Broker / market-data feeds** (future) can carry subscription fees; brokerage commissions are
  trading *capital*, not platform spend - keep the distinction clean.

## 3. What already exists, and the gap

- **Live:** the monthly `cost_reconciliation` job (`scripts/cost_reconciliation.py` +
  `config/agent/cost_reconciliation.yaml` + `.github/workflows/cost-reconciliation.yml`). It is an
  **anomaly alarm** (alarm-not-gate, Decision 55): it ingests a **manually-exported** USD invoice
  snapshot from `s3://.../cost-invoices/<month>.json`, evaluates five thresholds, and files/closes
  recs. It models DeepSeek + Anthropic + AWS; it does **not** model Neon.
- **Not live:** `terraform/cost_monitoring.tf` (AWS Budgets + Cost Anomaly Detection + a CloudWatch
  cost dashboard) sits at the **legacy repo root** and is **not applied** (only `terraform/personal/`
  is live). So there are currently **no** AWS-native budget or anomaly alerts running.
- **Reference:** the `cost_projection` block (envelope + five `reevaluation_triggers`).

**The gap this capability fills:** there is no *unified, fresh, at-a-glance* view of variable
spend; the AWS bill is not auto-pulled (invoice export is manual); and Neon is unmodeled. The
existing alarm answers "did a threshold trip?", not "where is my money going, right now?".

## 4. Feasibility constraints (verified this session)

1. **No role can read AWS costs.** `PlatformDev` (the runtime `agent_platform` role) returns
   `AccessDeniedException` on `ce:GetCostAndUsage`; no CI or bootstrap role has any `ce:`/`budgets:`
   grant. A **net-new read-only cost role** is required.
2. **AWS CUR was deliberately retired** (CD.28) in favour of manual per-provider invoice export.
   Re-introducing a programmatic AWS cost read (Cost Explorer `GetCostAndUsage`) is a conscious
   reversal of that source choice and should be recorded as such at build time.
3. **No private web surface exists** anywhere in the repo - a private, authenticated, data-backed
   page is a **net-new architectural primitive**.
4. **The public `theseus.support` surface cannot carry cost data.** The Theseus/Semanto brand
   (Decision 101, roadmap `ROADMAP-SEMANTO.yaml`, all `deferred_post_mvp`) provisions a **public**
   Cloudflare Pages marketing site; the public-content boundary (Decisions 73/83/101) bars it from
   AWS account specifics and `docs/`/`logs/` content, and the owner confirmed the domain is
   public-only. Cost figures stay off it.
5. **Anthropic exposes a usage/cost API** (`/v1/organizations/usage`, referenced by CD.28's
   Tier-2 credential-validation discipline point); DeepSeek and Neon usage/consumption APIs need
   confirming at build time.

## 5. Architecture: data rests in AWS, the dashboard is a projection

The load-bearing design choice (owner's call): **confidential cost data rests in the personal AWS
account (private S3); the dashboard is a read-only projection of it.** Storing spend data on a
third party is treated as an anti-pattern, and it keeps the design fully inside the existing
73/83/101 boundary with no decision to ratify.

Five components:

1. **Cost-read role** - a net-new, read-only AWS IAM role granting `ce:GetCostAndUsage` (scoped,
   billing-read only). IAM-sensitive: provisioned in `terraform/personal` via the admin / gated
   `tf-gated-apply` path for a boundary-carrying `agent-platform-*` role (Decision 98, amended by
   Decision 144), and the new `ce:` namespace extends the Decision 129/144 read-coverage verifier.
2. **Daily pull** - a scheduled job (a Lambda + EventBridge, or a daily GitHub Action reusing the
   monthly reconciliation's pattern) that pulls AWS Cost Explorer + the per-vendor billing/usage
   APIs. Provider credentials live in Secrets Manager (the T0.4 pattern). **The Neon leg uses
   Neon's billing/management HTTPS API, never a DuckLake catalog ATTACH/query** - a catalog query
   would inflate the very egress it measures (Decision 88).
3. **Private snapshot** - the pulled figures land as a USD JSON snapshot in **private S3**
   (`s3://agent-platform-data-lake/cost-snapshots/...`), never the repo.
4. **Projection** - a renderer turns the snapshot into a small static HTML page (spend by vendor +
   a simple proportion chart), written to **private S3**. Loud-fail, never silent substitution
   (Decision 55): each rendered line is labelled by source, and a present-but-unparseable snapshot
   warns rather than degrading to an estimate.
5. **Private access** - viewed via a **presigned URL** (the time-limited link is the access gate)
   or the S3 console. No CloudFront/Cognito/Cloudflare, no new vendor, no boundary change.

### Managed-native discipline (Decisions 100/75)

Native primitives own their surfaces, so the build must not hand-roll around them: AWS-side data
comes from `ce:GetCostAndUsage` and the per-vendor billing APIs (never console scraping), and
AWS-side *alarming* should use native **AWS Budgets + Cost Anomaly Detection**, not a bespoke
detector. The one thing with no native equivalent - and the recorded justification for a custom
component - is the **unified cross-vendor private projection** (AWS plus three non-AWS vendors in a
single private view). That is what this item builds, and nothing more.

### Hosting ladder considered

| Option | Where data rests | Verdict |
|---|---|---|
| **A0 - private S3 + presigned URL** (chosen MVP) | AWS | Least architecture; boundary intact; a link you open, not a standing URL. |
| C - Cloudflare Access front, data in AWS | AWS | A standing `theseus.support`-style URL, boundary intact, more plumbing. Future upgrade. |
| B - Cloudflare Pages tenant holds the data | Cloudflare | **Rejected** - extends the 73/83/101 confidential-data boundary; owner declined storing data off-AWS. |

### Side-benefit

The same cost-read role lets the **existing monthly `cost_reconciliation` job auto-pull AWS**
instead of the owner hand-exporting an invoice - retiring a manual chore. This is a concrete,
standalone reason the cost-read role has value even ahead of the full dashboard.

## 6. Timing and placement

- **Status: `deferred_post_mvp`.** The dashboard's value scales with spend, and the spend that
  grows is post-MVP (executor unfreeze; data volume; live trading). Built today it tracks noise.
- **Activation trigger:** variable spend becomes *material* - the frozen executor (Decision 67)
  unfreezes and LLM-API spend is non-trivial, **or** the monthly reconciliation begins tripping
  its thresholds regularly. This is a more honest "when" than a fixed calendar slot.
- **Priority vs Semanto:** precedes the Semanto marketing surface (operational introspection
  before external marketing), but has **no dependency** on it - different surfaces (private-AWS vs
  public-Cloudflare). Recorded as a priority note, not an ordering edge.
- **Cheapest early option (independent):** AWS Budgets + Cost Anomaly Detection *alerts* (~free,
  managed, push not pull) can be pulled forward anytime as a proactive spend-spike guard, without
  any of the dashboard build. Not proposed now; on record as the low-cost early lever.

## 7. Known gaps / open questions for the eventual build

- Confirm the DeepSeek and Neon usage/consumption API endpoints + auth; confirm the Anthropic
  usage-API scope and whether an admin key (distinct from the T0.4 inference key) is needed.
- Re-ground the stale `anthropic_pool_size_usd` baseline (Max x5 -> Max x20) - owner-owned edit.
- Decide the scheduler substrate (Lambda + EventBridge vs daily GitHub Action) and the renderer.
- Decide the presigned-URL lifecycle (regenerate on each daily run vs on demand).
- Decide whether to fold `scripts/cost_reconciliation.py` into a `scripts/cost/` subpackage at
  reactivation (it would become the 3rd cost module; `scripts/CLAUDE.md` subpackage rule).
- Whether to record a Decision at build time for the CUR-reversal (programmatic AWS cost read) and
  the "cost data is a private-AWS projection; never on the public domain" guardrail.

## 8. Explicitly not doing (this session or this item)

Building the dashboard; the Theseus/Semanto rebrand (a separate roadmap); currency handling; and
any tracking of the Claude Code subscription.

## 9. Decisions honoured

Public-content / confidential-data boundary: **73, 83, 101** (curated public portal, **111/CD.20**)
- no cost figures in the repo. Agent-first / prose taxonomy: **86, 127** (this report is the
allowed spike-note class; forward intent lives in T2.51, not restated here). Deferred-item
governance: **93** (MVP boundary; activation trigger is a narrative condition, not a `depends_on`
edge). Structured criteria: **136/CD.39**. Roadmap ceiling: **114**. Plan schema: **85**. STRATEGIC
freeze: **67/CD.17** (item is `strategic:false`; realization decomposes into IMPLEMENTATION plans).
Cost-substrate + triggers: **CD.28/122**. Neon egress: **88** (billing API, not a catalog query).
Managed-native: **100/75**. Alarm-not-gate / loud-fail: **55, 62/CD.12**. Cost-read IAM role:
**98 (amended 144)**. No candidate decision is engaged (**105**) - the design derives from the
existing boundary, so there is no architectural fork to ratify.
