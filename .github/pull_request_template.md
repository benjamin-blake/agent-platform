## Summary

<!-- One line: what this PR does and why. -->

## Changes

<!-- Bullet list of substantive changes. Focus on the what and why, not the how. -->

-

## Verification

<!-- What you ran and the result. The authoritative gate is the pr-validate + terraform-validate
     CI checks (Decision 83); this section is advisory context for reviewers. -->

- `bin/venv-python -m scripts.validate --pre` -- exit 0

## Decisions

<!-- Optional. Decision IDs this change references or is gated by (e.g. Decision 73, Decision 101).
     Omit this section if no decisions apply. -->

## Resolves

<!-- If this PR closes one or more recommendations, add the trailer to the SQUASH-MERGE commit body
     (not just the PR description -- GitHub auto-populates the body, but rec-autoclose.yml parses
     the squash-merge commit message):

     Resolves: rec-NNNN[, rec-MMMM]

     See AGENTS.md "Resolves: trailer" and the ops_data_portal fallback (Decision 70).
     Omit this section if the PR resolves no recs. -->

---

<!-- PUBLIC-REPO BOUNDARY (Decision 101): Never include AWS account IDs / ARNs, IAM ExternalIds,
     secrets / API keys, trading alpha / strategy performance data, or internal hostnames that
     provide an attack surface. See AGENTS.md "PUBLIC repository / confidential-data boundary".

     COMMIT-MESSAGE CONVENTIONS: feat({slug}), plan({slug}), roadmap({ids}), scope({slug}).
     See AGENTS.md "Commit-message conventions".

     Drop any section above that does not apply to this PR. -->
