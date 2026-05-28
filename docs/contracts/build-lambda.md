# Boundary Contract: build_lambda.py

## Tool
`scripts/build_lambda.py` -- Lambda zip packaging utility

## Input Semantics

| Argument | Semantics | Correct Use |
|----------|-----------|-------------|
| `--handler` | Entry point module path relative to `src/` | Must follow the `src/data/handlers/{name}_handler.py` convention |
| `--output` | Destination path for the zip file | Usually `lambda-packages/{name}.zip` |
| `--layer` | Lambda layer flag to include external dependencies | Include when handler uses yfinance, pyyaml, or other extras |

## What We Send
Handler paths following the convention `src/data/handlers/{name}_handler.py`. Example:
```bash
python scripts/build_lambda.py --handler src/data/handlers/fetch_handler.py --output lambda-packages/fetch.zip
```

## Why This Delivery Mechanism Is Correct
AWS Lambda resolves the handler as `{module}.{function}` where the module path maps to the Python import. If the handler path does not match the deployed file structure, Lambda fails at import time with "Unable to import module".

## What Would Go Wrong If Semantics Differ
A mismatched `--handler` path causes Lambda to fail silently at cold start with:
```
[ERROR] Runtime.ImportModuleError: Unable to import module '{wrong_path}': No module named '{wrong_name}'
```
This only surfaces at invocation time, not during local `zip` creation.

## Date Last Verified
2026-04-08

## Related Gotcha
See Terraform lambda module configuration in `terraform/data_pipeline.tf` (handler field must match zip contents).

## Verified
This contract reflects the AWS Lambda Python handler conventions documented at
https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
