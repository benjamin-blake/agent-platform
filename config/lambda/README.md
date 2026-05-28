# config/lambda/

Per-Lambda runtime payloads. Each subdirectory corresponds to one Lambda function and is
bundled into `<name>.zip` by `scripts/build_lambda.py`. Files here are deployed to AWS Lambda.

Shared runtime config (loaded by `src.common.config` at runtime) stays at `config/config.yaml`.
Agent-only config (DQ rules, executor prompts, copilot registry, IAM manifest) lives under
`config/agent/` and is NOT bundled into any Lambda zip.
