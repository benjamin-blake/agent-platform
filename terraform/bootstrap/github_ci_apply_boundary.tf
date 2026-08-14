# github_ci_apply authority-budget boundary policy -- split from github_ci_apply.tf
# (Decision 166 terraform-class grandfather drain, PLAN-terraform-decompose-oidc-rename).
#
# rec-2793 (DEP-01 anti-recurrence), extended to the boundary document: hoisted out of the
# aws_iam_policy resource's inline `policy = jsonencode({...})` attribute so the lifecycle
# precondition below can self-reference the rendered JSON (a precondition cannot reference `self` --
# that is postcondition-only).
locals {
  github_ci_apply_boundary_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Permissive Allow on all data-plane services github_ci_apply uses. A boundary is a ceiling
        # -- it cannot grant more than the identity policy allows. This broad Allow ensures legitimate
        # data-plane capabilities are not silently capped by the boundary (boundary-too-tight silently
        # breaks the pipeline; verified via simulate-principal-policy VP11 "dataplane: allowed").
        # Includes IAM read/OIDC/tag actions and the bounded IAM write actions; DenyIAMEscalation
        # below narrows the write actions at the call site.
        Sid    = "DataPlaneAllow"
        Effect = "Allow"
        Action = [
          "s3:*",
          "athena:*",
          "glue:*",
          "dynamodb:*",
          "lambda:*",
          "logs:*",
          "events:*",
          "sns:*",
          "cloudwatch:*",
          "secretsmanager:*",
          "ssm:*",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:GetOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:CreateRole",
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy",
          "iam:PutRolePermissionsBoundary",
          # DEP-01 / HAZARD-4 (Decision 144): the boundary is a CEILING -- the 4 new iam verbs the
          # widened identity policy grants (IAMRoleDeleteBounded's three destroy verbs +
          # IAMRoleDescriptionWrite's UpdateRoleDescription) must ALSO be permitted here, or they are
          # silently denied by the intersection. DenyIAMEscalation below still narrows the
          # create/put/attach write actions at the call site; the destroy verbs are gated by the guard.
          "iam:DeleteRole",
          "iam:DetachRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:UpdateRoleDescription",
          # DEP-02 (Decision 144, rec-2842): the boundary ceiling for the new IAMRoleMetadataWrite
          # identity Sid above. iam:TagRole / iam:UntagRole are already ceiling-covered by the
          # pre-existing entries above (moved here unchanged from the old IAMRoleReconcile grant);
          # iam:UpdateRole is the one NEW verb this Sid adds (Fable's predicted next gap --
          # max_session_duration edits AccessDeny at both layers today with no covering grant). A
          # grant absent from the boundary ceiling is silently denied by the identity/boundary
          # intersection.
          "iam:UpdateRole",
          # rec-2831 (DEP-01 completion, T2.48 c1, PLAN-t248-passrole-liveproof): the boundary
          # ceiling for the IAMPassRoleForLambda identity grant above. The identity policy already
          # worst-verb-scopes PassRole (role/agent-platform-* + PassedToService=lambda.amazonaws.com);
          # the boundary Allow itself stays unconditioned here, matching the existing pattern for
          # every other IAM write verb in this same list (CreateRole/PutRolePolicy/AttachRolePolicy
          # are narrowed by the separate DenyIAMEscalation Deny below, not by a Condition on this
          # Allow) -- a boundary is a ceiling, not a second copy of the identity-side scoping.
          # DenyIAMEscalation / DenyBoundaryRemoval / DenyBoundaryPolicyModification below stay
          # non-intersecting with PassRole (verified live by the bootstrap simulate-gate, VP step 10).
          "iam:PassRole",
          # rec-2882 (P0-1) + P1-4: the ceiling half of the three new iam verbs the identity policy
          # grants above -- IAMRoleDeleteBounded's iam:ListInstanceProfilesForRole and
          # IAMInstanceProfileDetach's iam:RemoveRoleFromInstanceProfile (the provider's deleteRole()
          # unconditionally calls deleteRoleInstanceProfiles(), which issues both -- they sit in two
          # Sids because the second authorizes on the instance-profile resource type, not the role;
          # this ceiling is unaffected, its Resource is the bare wildcard. NOTE, and do not undo it:
          # a comment INSIDE this Action array must contain NO square bracket of either kind -- the
          # checks parse the array with a non-greedy Field-equals-bracket regex, so one stray closing
          # bracket truncates the parsed ceiling; if the comment also quotes a bare star, the
          # truncated list ends in a wildcard and EVERY boundary assertion passes vacuously. This
          # rule cost a real debugging round.) and OIDCProviderReconcile's
          # iam:UntagOpenIDConnectProvider (tag-drift reconcile). A grant present in only ONE layer
          # is silently denied by the identity/boundary intersection -- that single-layer silence is
          # the failure mode this whole change exists to end, so these are added in the same edit as
          # the identity grants, never afterwards. None is escalation-relevant: the two role verbs
          # only detach a role from an instance profile (this account provisions no EC2 instance
          # profiles at all, so they are inert outside the destroy path) and the third is tag
          # metadata. Destroys still ROUTE to gated-apply -- the guard is unchanged.
          "iam:ListInstanceProfilesForRole",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:UntagOpenIDConnectProvider"
        ]
        Resource = ["*"]
      },
      {
        # Deny IAM escalation: CreateRole/PutRolePolicy/AttachRolePolicy without the authority budget.
        # StringNotEquals on iam:PermissionsBoundary: if the key is absent from the request context
        # (unbounded create/put), StringNotEquals evaluates to true -> Deny applies. Belt-and-suspenders
        # with the identity policy's conditional Allow (IAMRoleCreateBounded / IAMRoleWriteBounded).
        # SIMULATE ARTIFACT -- NOT A GAP, DO NOT "FIX" IT (recorded so a future auditor does not
        # chase a false positive): iam:simulate-principal-policy returns explicitDeny/implicitDeny
        # for iam:CreateRole / iam:PutRolePolicy / iam:AttachRolePolicy / iam:PutRolePermissionsBoundary
        # ONLY when the iam:PermissionsBoundary context entry is OMITTED from the simulate call --
        # which is precisely this statement working as designed, because an omitted key makes
        # StringNotEquals true. Supply the boundary ARN as a context entry and the same four verbs
        # come back allowed. Any "completion" of these verbs based on a context-free simulate would
        # be granting against a control that is functioning correctly.
        Sid    = "DenyIAMEscalation"
        Effect = "Deny"
        Action = [
          "iam:CreateRole",
          "iam:PutRolePolicy",
          "iam:AttachRolePolicy"
        ]
        Resource = ["*"]
        Condition = {
          StringNotEquals = {
            "iam:PermissionsBoundary" = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
          }
        }
      },
      {
        # Deny boundary removal from any role: prevents the pipeline from stripping the authority
        # budget from itself or from any role it manages.
        Sid      = "DenyBoundaryRemoval"
        Effect   = "Deny"
        Action   = ["iam:DeleteRolePermissionsBoundary"]
        Resource = ["*"]
      },
      {
        # Deny boundary self-modification: the pipeline cannot edit or delete the authority budget
        # policy document that constrains it. The boundary policy ARN is a literal to avoid a
        # circular resource reference.
        Sid    = "DenyBoundaryPolicyModification"
        Effect = "Deny"
        Action = [
          "iam:CreatePolicyVersion",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:SetDefaultPolicyVersion"
        ]
        Resource = [
          "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary",
          # Policy-architecture split: the 11 relocated read Sids now live in the customer-managed
          # agent-platform-github-ci-apply-reads document. Naming it HERE is what keeps those grants
          # behind the same EXPLICIT Deny that protects the boundary document. Without this entry the
          # relocation would silently downgrade their protection in KIND -- from an explicit Deny to
          # the mere ABSENCE of an iam:CreatePolicy* grant, which any later grant edit (or a widened
          # iam verb family) could re-enable with nothing failing loudly. An explicit Deny cannot be
          # overridden by any Allow, so a version of the reads document rewritten by the pipeline
          # itself is impossible rather than merely un-granted. Literal ARN for the same reason as
          # the boundary's (no circular resource reference).
          "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-reads",
        ]
      }
    ]
  })
}

resource "aws_iam_policy" "github_ci_apply_boundary" {
  name        = "agent-platform-github-ci-apply-boundary"
  description = "Authority budget for github_ci_apply: permissive data-plane Allow + IAM escalation Deny (CD.35 Wave 4 / T2.23)."
  policy      = local.github_ci_apply_boundary_policy_json

  lifecycle {
    precondition {
      # rec-2793, applied to the boundary document: AWS excludes whitespace from the 6,144 B
      # customer-managed-policy limit (distinct from the 10,240 B inline-policy limit), so measure
      # the WHITESPACE-STRIPPED/minified rendering -- a raw whitespace-inclusive length() here
      # false-fails on the indented HCL rendering of a document that deploys fine minified. A
      # LimitExceeded is invisible to `terraform plan` and surfaces only at apply.
      condition     = length(jsonencode(jsondecode(local.github_ci_apply_boundary_policy_json))) <= 6144
      error_message = "github_ci_apply boundary policy exceeds the 6,144 B managed-policy limit (whitespace-stripped measure, rec-2793). Trim grants -- never raise the constant; it is an AWS hard limit."
    }
  }
}
