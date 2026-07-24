# REPORT: Private variable-cost visibility dashboard (scoping)

> Scoping / spike note for platform tier item **T2.51** and candidate decision **CD.41**. Not an
> implementation. Captures the cost-proportion analysis, the architecture (a private dashboard
> whose data stays in AWS and whose auth front is Cloudflare Access, under a fenced boundary
> carve-out), and the timing rationale behind placing the capability on the roadmap as
> `deferred_post_mvp`. The roadmap entry (T2.51) is the canonical forward intent and CD.41 is the
> pattern decision; this report is the design rationale they point back to.

## 1. Scope decision

This scopes visibility for **variable operational vendor spend only**:

- **In scope:** AWS (all services), the LLM inference APIs (DeepSeek Tier 1, Anthropic-direct
  Tier 2), and Neon (the DuckLake catalog).
- **Out of scope (deliberately):** the Claude Code Max subscription. It is a fixed line the owner
  tracks out-of-band, and excluding it is *more* future-proof, not less: as the platform shifts
  from the subscription/OAuth model to metered API rates, agent-inference spend becomes a metered
  Anthropic/DeepSeek line that a variable-spend tracker already covers.
- **Consequence:** every in-scope line is billed in **USD**, so there is no currency-conversion
  layer to build.

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
time; it is not worth building to itemise today's flat spread of single-digit-dollar lines.

### What is easy to forget (the "what am I missing" answer)

- **Anthropic API direct** is a distinct line from the subscription. The Tier-2 escape hatch is
  funded by the Max programmatic-pool credit (part of the *excluded* subscription); the actual
  *variable* Anthropic spend this dashboard would track is the **deferred org-billed Anthropic API
  key** (CD.28's cost-monitoring follow-on), which bills at API rates. The reconciliation baseline
  (`anthropic_pool_size_usd: 100.0`, "Max x5") should be re-grounded against the owner's current
  subscription tier when this is built. The dashboard's pulls also feed CD.28's `cost_projection`
  reevaluation triggers (DeepSeek pricing >5x; pool >70% over 30d).
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
  is live). So there are currently **no** AWS-native budget or anomaly alerts running, and the
  CloudWatch billing dashboard defined there is not deployed.
- **Reference:** the `cost_projection` block (envelope + five `reevaluation_triggers`).

**The gap this capability fills:** there is no *unified, fresh, at-a-glance* view of variable
spend; the AWS bill is not auto-pulled (invoice export is manual); and Neon is unmodeled. The
existing alarm answers "did a threshold trip?", not "where is my money going, right now?".

## 4. Feasibility constraints (verified this session)

1. **No role can read AWS costs.** `PlatformDev` (the runtime `agent_platform` role) returns
   `AccessDeniedException` on `ce:GetCostAndUsage`; no CI or bootstrap role has any `ce:`/`budgets:`
   grant. A **net-new read-only cost role** is required.
2. **Cost-source framing (corrected).** LLM spend (DeepSeek/Anthropic-direct) is billed by the
   providers *outside* AWS, so AWS Cost Explorer/CUR structurally cannot capture it - per-provider
   invoice/usage export is authoritative for the LLM legs (this is the narrow, real meaning of the
   "AWS CUR no longer captures LLM spend" note in `INTENT-provider-agnostic-executor.md`, a
   consequence of the Bedrock->direct-API move). For the **AWS-infrastructure** leg (S3, Lambda,
   CloudWatch, etc.), a programmatic Cost Explorer read (`ce:GetCostAndUsage`) is a **new source
   choice** - no decision governs AWS-infra cost sourcing, so it is *not* a reversal of CD.28.
   Record it as a fresh source Decision at build time.
3. **No private web surface exists.** A private, authenticated, human-viewable page is a net-new
   architectural primitive. (Note: `terraform/cost_monitoring.tf` defines an AWS-native CloudWatch
   *console* cost dashboard, unapplied - that covers the AWS leg inside the AWS console, but is not
   a hosted cross-vendor page.)
4. **The public `theseus.support` surface stays public-only** and never carries cost data
   (Decisions 73/83/101; the owner confirmed the domain is public). The private dashboard is a
   separate surface.
5. **Anthropic exposes a usage/cost API** (`/v1/organizations/usage`, referenced by CD.28's
   Tier-2 credential-validation discipline point); DeepSeek and Neon usage/consumption APIs need
   confirming at build time. **The Neon leg must use Neon's billing/management HTTPS API, never a
   DuckLake catalog ATTACH/query** - a catalog query would inflate the very egress it measures
   (Decision 88).

## 5. Architecture: data stays in AWS; Cloudflare authenticates only

The owner wants a bookmarkable experience: open a tab, authenticate, view. The chosen shape
(option "2b", validated by a Fable advice-consult) delivers that while keeping **all confidential
data and every credential inside AWS**. It is codified as **CD.41** (Section 5.3).

### 5.1 Data plane (identical regardless of how the dashboard is served)

1. **Cost-read role** - a net-new, read-only AWS IAM role granting `ce:GetCostAndUsage` (scoped,
   billing-read only). IAM-sensitive: provisioned in `terraform/personal` via the admin / gated
   `tf-gated-apply` path for a boundary-carrying `agent-platform-*` role (Decision 98, amended by
   Decision 144). *Open question:* confirm at build time whether a `ce:` billing role falls under
   the Decision 129/144 read-coverage verifier (it may sit outside its data-plane scope).
2. **Daily pull** - a scheduled job (a Lambda + EventBridge, or a daily GitHub Action reusing the
   monthly reconciliation's pattern) that pulls AWS Cost Explorer + the per-vendor billing/usage
   APIs (Anthropic usage API; DeepSeek; **Neon via its billing/management HTTPS API, not a catalog
   query**). Provider credentials live in Secrets Manager (the T0.4 pattern).
3. **Snapshot (grain-first)** - the pulled figures append to a private-S3 store, **grain: one row
   per vendor per day**, append-only, event-time-partitioned. Retention keeps a rolling window so
   the projection can show a **trend** (see 5.2), not just a point-in-time slice. Never the repo.
4. **Projection** - a renderer turns the snapshot history into a small static dashboard: spend by
   vendor **and its trend over time** (the two-whales lens of Section 2). Loud-fail, never silent
   substitution (Decision 55): each line is labelled by source (`measured` vs
   `list-price-estimate`); a present-but-unparseable snapshot warns rather than degrading to an
   estimate; and a **stale/absent snapshot** (a silently-failed daily pull - the worst failure
   mode) raises a rec via the existing alarm-not-gate path rather than showing stale numbers as
   current.

The renderer is **agnostic**: any tool that emits a static artifact at rest in S3 qualifies (a
script emitting HTML, a static-site generator, a notebook export, a pre-built SPA). The MVP
instance is a static pre-rendered projection; whether it is a single self-contained object or a
multi-file static site is an implementation choice constrained only by the CD.41 invariant (5.3) -
a multi-file static site is served from a direct-from-AWS origin rather than a single presigned
object (see 5.4 open question). "Static pre-rendered" is the MVP instance, **not** a constraint of
the pattern.

### 5.2 Access plane (the bookmarkable experience) - option 2b

- `costs.theseus.support` (a private subdomain, separate from the public marketing site) is gated
  by **Cloudflare Access** (Zero-Trust: the owner's single email via Google / one-time-PIN).
- Behind it, an **in-AWS Lambda** verifies the `Cf-Access-Jwt-Assertion` against the Access JWKS +
  AUD, then mints a **<=5-minute presigned S3 GET** using its **own execution-role STS creds** and
  302-redirects. The browser fetches the artifact **directly from S3** (AWS <-> browser).
- **No AWS credential ever rests outside AWS.** The Lambda signs in-account; Cloudflare holds zero
  AWS material. **Dual enforcement:** the Lambda independently rejects any request without a valid
  Access JWT, so AWS is a real gate even if the redirect URL leaks - Cloudflare is UX, not the sole
  control.

Experience: bookmark `costs.theseus.support`, open, Access login (cached thereafter), view. The
confidential figures **never transit Cloudflare** - it sees the auth event and a short-lived,
single-object, read-only capability redirect, nothing more.

### 5.3 The boundary carve-out (CD.41) - fenced on the invariant, not the data

Putting a Cloudflare-Access front on a private dashboard extends the 73/83/101 confidential-data
boundary, so it is recorded as a candidate decision. Per the owner's DRY point, CD.41 is fenced on
the **architectural invariant, not the data type**, so it is a single reusable pattern (this cost
dashboard is its first tenant), not a cost-only exception that would force a second hosting stack:

> **The pattern is approved for any private dashboard provided:** (a) no AWS credential ever rests
> outside AWS; (b) the confidential payload never transits Cloudflare (it flows AWS->browser); (c)
> AWS independently re-verifies the Access token. Any implementation breaking (a)/(b)/(c) - a
> Cloudflare Worker holding an AWS key, Cloudflare terminating TLS on the payload ("2a"), or the
> data resting on Cloudflare - is out of scope and requires a fresh Decision.

Because the fence is on the safe *shape*, the precedent cannot be cited to justify the unsafe
variants for hotter data. The one thing genuinely different about higher-consequence data (trading
alpha/performance) is not the pattern's security but the *cost of a residual failure* (a leaked AWS
bill is mild; leaked alpha is catastrophic). So CD.41 permits reuse for any data under the same
invariant, but requires that **extending it to catastrophic-consequence data triggers a deliberate
hardening review** (tighter TTL, IP allowlist, client-bound links, or a non-internet-facing front)
- an added defense-in-depth layer on the *same* pattern, not a second pattern, and a conscious
pause rather than an auto-inherited grant.

**Mitigations (CD.41 discipline points):** in-AWS signing only; dual enforcement; presigned TTL
<= 5 min on a self-contained no-store object with Block-Public-Access on; single-email Access
policy with short sessions and Access logging; a CloudTrail S3 data-event alert on the dashboard
prefix for unexpected principals. **Reversal:** if the carve-out is ever deemed not worth the
third-party auth dependency, fall back to Option 1 (5.4) - a read-only projection, so migration is
plumbing with zero data movement.

### 5.4 Alternatives considered

| Option | Where data rests / transits | Verdict |
|---|---|---|
| **2b - Cloudflare Access auth + in-AWS signing + direct-to-S3** (chosen) | Rests and transits only in AWS; Cloudflare sees auth + a redirect | Chosen. Bookmarkable, boundary-clean under CD.41's invariant. |
| 2a - Cloudflare Worker proxies the data | Transits Cloudflare's edge (TLS-terminated) | **Rejected** - a proxy that sees every byte "has" the data; also needs a standing AWS key at Cloudflare. |
| 1 - AWS-native (CloudFront + Cognito / Amplify) | 100% AWS; no third party in the auth path | Fallback. Zero-exception purity, but real Cognito/edge complexity, and Cloudflare still runs the DNS regardless. |
| B - Cloudflare Pages holds the rendered page | Rests on Cloudflare | **Rejected** - data off-AWS (owner's declared anti-pattern). |
| A0 - private S3 + presigned/console only | AWS | Degenerate fallback - no bookmarkable URL; presigned links under temp creds expire in hours. |

**Open question (build time):** a multi-file static-site renderer needs its serving reconciled
with invariant (b) - the clean single-object presigned redirect does not cover a multi-asset site,
so a multi-file build is served from a direct-from-AWS origin (e.g. CloudFront/OAC) that still
keeps the payload off Cloudflare. Resolve when the renderer is chosen; it does not change CD.41.

### 5.5 Side-benefit

The same cost-read role lets the **existing monthly `cost_reconciliation` job auto-pull AWS**
instead of the owner hand-exporting an invoice - retiring a manual chore. Wiring: the new role must
be assumable by the reconciliation job's OIDC principal (`agent-platform-github-ci-branch`), or the
`ce:` grant added to that role; name the choice in the build plan.

## 6. Timing and placement

- **Status: `deferred_post_mvp`.** The dashboard's value scales with spend, and the spend that
  grows is post-MVP (executor unfreeze; data volume; live trading). Built today it tracks noise.
- **Activation trigger:** variable spend becomes *material* - the frozen executor (Decision 67)
  unfreezes and LLM-API spend is non-trivial, **or** the monthly reconciliation begins tripping
  its thresholds regularly.
- **Priority vs Semanto:** precedes the Semanto marketing surface (operational introspection
  before external marketing), but has **no dependency** on it - different surfaces (private-AWS +
  Cloudflare-Access vs public-Cloudflare-Pages).
- **Cheapest early option (independent):** AWS-native **Budgets + Cost Anomaly Detection** alerts,
  plus porting the unapplied CloudWatch billing dashboard (`terraform/cost_monitoring.tf`) into
  `terraform/personal`, give a proactive AWS-side spend-spike guard with no dashboard build. On
  record as the low-cost early lever; native primitives own AWS-side alarming (Decisions 100/75).

## 7. Known gaps / open questions for the eventual build

- Confirm the DeepSeek and Neon billing/usage API endpoints + auth; confirm the Anthropic
  usage-API scope and whether an admin key (distinct from the T0.4 inference key) is needed.
- Record a fresh **source Decision** for the programmatic AWS-infra Cost Explorer read (Section 4.2
  - a new source choice, not a CD.28 reversal).
- Re-ground the stale `anthropic_pool_size_usd` baseline against the owner's current subscription
  tier - owner-owned edit.
- Reconcile the multi-file static-site serving with CD.41 invariant (b) (Section 5.4).
- Confirm whether the `ce:` role falls under the Decision 129/144 read-coverage verifier.
- Decide the scheduler substrate (Lambda + EventBridge vs daily GitHub Action) and the renderer;
  correct the stale Neon `$0 free tier` line (ROADMAP `cost_projection`).

## 8. Explicitly not doing (this session or this item)

Building the dashboard; choosing/naming the specific renderer or BI tool (an owner hypothesis, held
out of scope); the Theseus/Semanto rebrand (a separate roadmap); currency handling; and any
tracking of the Claude Code subscription.

## 9. Decisions honoured

Public-content / confidential-data boundary: **73, 83, 101** (curated public portal, **111/CD.20**)
- no cost figures in the repo; the public domain never carries cost data. Boundary carve-out for
the private dashboard: **CD.41** (new, invariant-fenced, reversible; Fable-advice-consulted).
Agent-first / prose taxonomy: **86, 127** (this report is the allowed spike-note class; forward
intent lives in T2.51, not restated here). Deferred-item governance: **93** (activation trigger is
narrative, not a `depends_on` edge). Structured criteria: **136/CD.39**. Roadmap ceiling: **114**.
Plan schema: **85**. STRATEGIC freeze: **67/CD.17** (`strategic:false`; realization decomposes into
IMPLEMENTATION plans). Cost-substrate + triggers: **CD.28/122** (LLM spend is provider-billed, not
AWS-CUR-captured; the AWS-infra Cost Explorer read is a *new* source choice, not a CD.28 reversal).
Neon egress: **88** (billing API, not a catalog query). Managed-native: **100/75** (native AWS
Budgets/Anomaly for AWS-side alarming; only the cross-vendor private view is custom). Alarm-not-gate
/ loud-fail: **55, 62/CD.12**. Cost-read IAM role: **98 (amended 144)**; read-coverage verifier
scope: **129/144** (open question).
