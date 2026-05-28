# DynamoDB Counters Table
# Provides atomic ID allocation for rec IDs, decision IDs, and other sequential counters.
# Accessed via SSO profile -- no IAM users (Decision 36/37).
# See docs/plans/PLAN-platform-ops-data-pipeline.md and rec-521.

resource "aws_dynamodb_table" "counters" {
  name         = "agent-platform-counters"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "counter_name"

  attribute {
    name = "counter_name"
    type = "S"
  }

  tags = {
    Project     = var.project_name
    Purpose     = "Atomic sequential counter allocation for agents and executor"
    Phase       = "Phase_Platform"
    ManagedBy   = "Terraform"
    Environment = var.environment
  }
}
