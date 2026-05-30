# Partial S3 backend config for the sandbox PLATFORM environment (Decision 77).
# Account-agnostic: holds no account ID. Consumed via:
#   terraform init -backend-config=backend-sandbox.hcl
# A future SIT/PROD environment is a new backend-<env>.hcl with a different key (single-account
# until the product live_full trigger per docs/contracts/environment-taxonomy.md section 4).
bucket       = "agent-platform-data-lake"
key          = "tfstate/personal/sandbox/terraform.tfstate"
region       = "eu-west-2"
encrypt      = true
use_lockfile = true
