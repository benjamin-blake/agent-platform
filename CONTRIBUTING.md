# Contributing

Theseus is source-available under the Business Source License 1.1. See
[`LICENSING.md`](LICENSING.md) for what that means and where the licence boundary sits.

## Current posture

This is a single-maintainer project and is not currently accepting outside pull requests. Issues
and discussion are welcome. If that changes, this file changes with it.

## Copyright and why it matters here

Read this section before opening a pull request, because it is the part with real consequences.

The maintainer offers Theseus under two licences: BUSL-1.1 to everyone, and a separate commercial
licence to anyone who needs production use before the Change Date. **Offering the same code under
two licences requires holding the copyright in all of it, or holding a licence broad enough to
sublicense it.**

GitHub's Terms of Service (section D.6, "inbound=outbound") place a contribution under the
project's *outbound* licence -- here, BUSL-1.1. That is enough to accept, use and redistribute a
contribution under BUSL-1.1. It is **not** enough to relicense that contribution commercially,
because BUSL-1.1 grants no right to sublicense. So inbound=outbound alone does not support dual
licensing.

Accordingly, any contribution accepted into this repository must come with an assignment of
copyright to the maintainer, or a licence grant broad enough to permit commercial relicensing. If
you are not willing to grant that, please do not open a pull request -- and please raise an issue
instead, which costs you nothing and may well be the better route anyway.

There is currently **no automated CLA or DCO mechanism** in this repository. Until one exists, a
contribution is accepted only by explicit agreement recorded in the pull request. A sentence in a
contributing guide is not a substitute for a signed agreement, and this file does not pretend
otherwise.

## Provenance of the existing code

Two facts are recorded here plainly rather than left for someone to discover:

1. **The sole-ownership premise has not been formally audited.** The maintainer authored or
   directed the work, but no repository-wide authorship audit has been run to confirm that no
   third-party contribution carries rights inconsistent with dual licensing.

2. **Most commits carry a `Co-Authored-By` trailer naming an AI assistant.** The project's own
   git-ops conventions mandate that trailer, and it keeps accruing. A trailer is an attribution
   convention, not an assignment of copyright, and the maintainer's position is that it does not
   create a competing rights holder. It is named here because a dual-licensing posture that rests
   on sole copyright ownership should not quietly omit it.

Both points are recorded in the decision log. Neither is presented as settled by this file.

## If you do contribute

- Read [`AGENTS.md`](AGENTS.md) first; it is the operative style and architecture guide.
- Every behaviour-changing edit needs an automated test that fails without the change.
- Run `bin/venv-python -m scripts.validate --pre` before opening a pull request.
- No secrets, account identifiers or internal hostnames in commits -- this repository is public
  and a pre-commit hook blocks them by shape.
