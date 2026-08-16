# Licensing

Theseus changed licence on 2026-08-15. The change is **forward-only**.

## The boundary

| Versions | Licence |
|---|---|
| Every version published up to and including commit `4de9df86e02b7eeccf58df83e74f6061fc1303e2` | Apache License 2.0 |
| Every version published after that commit | Business Source License 1.1 |

The Apache-2.0 text that governed the earlier versions is preserved verbatim in
[`LICENSE-APACHE`](LICENSE-APACHE). The current licence is in [`LICENSE`](LICENSE).

## What forward-only means

Every version published under Apache-2.0 **remains** under Apache-2.0, irrevocably. If you
obtained a copy of Theseus at or before the boundary commit, your rights under Apache-2.0 are
unaffected by this change and cannot be withdrawn by it. Nothing in the new licence makes any
retroactive claim over those versions.

The licence change applies only to versions published after the boundary commit.

## Why the repository was renamed in place

The repository was renamed `agent-platform` -> `theseus` immediately before the flip, in place
rather than by publishing a fresh repository under the new name. A fresh repository would have
conferred no additional legal protection: the Apache-2.0 snapshots are already published, and
whoever holds one holds it under Apache-2.0 no matter what happens to the repository they came
from. What a fresh repository would have destroyed is real -- the public commit and pull-request
history that this project's decision log references by number, and the redirects that keep every
old link resolving. The rename therefore preserves continuity and changes nothing about the
boundary above.

## Self-verifying rule

Commit SHAs churn when history is rewritten, so the boundary above is stated in a form that does
not depend on a single identifier surviving:

> Any commit of this repository **as published by the Licensor** whose root `LICENSE` file
> contains the Apache License 2.0 text is an Apache-2.0 version. Any commit **as published by the
> Licensor** whose root `LICENSE` file contains the Business Source License 1.1 text is a
> BUSL-1.1 version.

The qualifier "as published by the Licensor" is load-bearing and is not decoration. The rule
identifies licence status by the content of a file that a licensee can edit. Scoped to the
Licensor's own published history it is a reliable test; unscoped, a post-flip BUSL licensee could
revert `LICENSE` in their own copy and self-certify the result as Apache-2.0. Provenance, not file
content alone, is what makes the rule sound.

## Why this file is not named NOTICE

Apache-2.0 section 4(d) gives a root `NOTICE` file a specific meaning in redistribution: a
downstream Apache licensee must reproduce its attribution contents. Pre-flip snapshots of this
repository are Apache-licensed, so putting licence-boundary prose in a file named `NOTICE` would
be genuinely ambiguous for anyone redistributing one of those snapshots -- they would face an
obligation to carry forward text describing a licence change that does not apply to what they
hold. This file is therefore `LICENSING.md`, which carries no such obligation.

## The Change Date

BUSL-1.1 is not an Open Source licence, but it converts to one. On the Change Date -- **2030-08-15**,
four years after the flip -- each version published under BUSL-1.1 becomes available under the
Apache License 2.0, the Change License named in `LICENSE`.

Under BUSL-1.1 the conversion is also capped independently: a version converts on the Change Date
or on the fourth anniversary of its own first publication, whichever comes first. A published
version's Change Date may be moved **earlier**, never later -- moving it later would be the same
kind of retroactive claim that the forward-only rule forbids in the other direction.

## Using Theseus

- **Non-production use** -- evaluation, research, internal development and testing, demonstration,
  and reading, modifying or redistributing the source -- is permitted by the licence. See the
  Additional Use Grant in [`LICENSE`](LICENSE) for the operative wording; the list there is
  illustrative and does not limit the rights the licence body grants.
- **Production use** requires a commercial licence until the Change Date. See
  [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md).
- **Contributing** -- see [`CONTRIBUTING.md`](CONTRIBUTING.md), which sets out the copyright
  position that dual licensing depends on.

## A note on licence detection

GitHub's licence detector is backed by choosealicense.com, which does not include BUSL-1.1 even
though it is a valid SPDX identifier (`BUSL-1.1`). GitHub may therefore show this repository's
licence as unrecognised. That is a limitation of the detector, not a statement about the licence.
