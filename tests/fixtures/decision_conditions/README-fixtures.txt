Fixture set for scripts/preflight/decision_conditions.py and
scripts/checks/ops_governance/validate_reversal_stanzas.py.

.txt extension (NOT .md) deliberately -- sidesteps validate_prose_allowlist, which scans
`git ls-files '*.md'` only (Decision 127). Each file is a standalone "DECISIONS.md-shaped"
document containing one or more '## Decision N: ...' headings, parseable by the same
_DECISION_HEADING_RE splitter scripts/decisions_md.py uses on the real DECISIONS.md /
DECISIONS_ARCHIVE.md files. Decision numbers here (901-908) are fixture-only and never collide
with a real ratified Decision.

Well-formed fixtures:
  past_review.txt              -- past review_by (2020-01-01) -> state manual-review-due.
  fired_predicate.txt          -- kind: repo_state condition naming a predicate the test injects
                                   via evaluate(predicates={...}) (never the production registry)
                                   -> state fired, proving fired outranks not-due/manual-review-due.
  not_due_133_like.txt         -- mirrors the real Decision 133 stanza SHAPE (a kind: manual
                                   first condition with only id/kind/description, plus kind:
                                   repo_state conditions carrying predicate: null) with a future
                                   review_by -> state not-due. A schema regression fixture,
                                   independent of the real DECISIONS.md content.
  prose_only.txt                -- a "**Reversal conditions:**" section with NO fenced stanza ->
                                   opt-out by absence: not monitored, not malformed, no state.

Malformed fixtures (each -> CLI nonzero exit + an explicit MALFORMED row naming the decision):
  malformed_bad_decision_key.txt   -- stanza 'decision:' field does not match the header number.
  malformed_unclosed_fence.txt     -- fence opens but is never closed before EOF.
  malformed_unknown_predicate.txt  -- repo_state condition names an unregistered predicate.
  malformed_bad_kind.txt           -- condition 'kind' is neither manual nor repo_state.

Two additional malformed variants named in the plan's execution_steps ("bad fence" via a
non-column-0 closing marker, and "non-loadable YAML" via invalid YAML syntax inside the fence)
are covered as INLINE fixtures in tests/test_decision_conditions.py rather than committed here --
they exercise the same MALFORMED code paths as the committed fixtures above (unclosed-fence
detection and yaml.safe_load error handling, respectively) and do not need a dedicated file that
PLAN-reversal-condition-monitor.yaml's verification_plan or the CLI references by path.
