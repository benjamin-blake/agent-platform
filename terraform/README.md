# Terraform Infrastructure

This directory contains Terraform configurations for AWS infrastructure supporting the dual-environment trading system.

## Architecture Overview

The infrastructure is split across two environments:

1. **Company Environment**: Formula discovery and research (SageMaker, Athena, S3)
2. **Personal Environment**: Live trading (Docker containers pull formulas from company S3)

## Infrastructure Components

### S3 Buckets (4)

- `formulas-discovery`: Raw formulas from SageMaker PySR
- `formulas-staging`: Formulas undergoing A/B testing
- `formulas-production`: Validated formulas for live trading
- `data-lake`: Iceberg tables for market data and backtest results

All buckets have:
- Versioning enabled (audit trail)
- AES-256 encryption
- Lifecycle policies (archive to Glacier after 90 days)

### Glue Catalog + Iceberg Tables

- `formula_lineage`: Complete formula lifecycle tracking (discovered → testing → staging → production → deprecated)
- `trading_performance`: Every trade execution for performance analysis
- `ab_test_results`: Statistical analysis of formula A/B tests
- `market_data`: OHLCV + computed features, partitioned by trade_date (MERGE upsert via awswrangler)
- `backtest_results`: Historical backtest outcomes for discovered formulas

Iceberg provides:
- Append-only audit trail
- Time travel (query historical states)
- Schema evolution
- ACID transactions

### CloudWatch Monitoring

**Dashboards:**
- Formula performance metrics (win rate, Sharpe ratio, circuit breakers)
- SageMaker job monitoring
- Cost tracking per service

**Alarms:**
- No active formulas in production
- Win rate < 40%
- Circuit breaker spikes (>5 in 1 hour)
- Ensemble latency > 100ms
- SageMaker job failures

### Cost Management

**Budgets:**
- Monthly total: $190 (alerts at 80% forecasted)
- SageMaker: $150/month
- Athena: $30/month

**Anomaly Detection:**
- AWS Cost Anomaly Detection with email alerts
- Daily cost reports via Lambda → Slack (optional)

### Data Pipeline (`data_pipeline.tf`)

**Step Functions state machine** orchestrating daily market data ingestion:

| Lambda | Purpose |
|--------|---------|
| `FetchMarketData` | Downloads FTSE 100 OHLCV from yfinance → raw Parquet in S3 |
| `ComputeFeatures` | Reads raw Parquet, computes ~18 technical features → enriched Parquet |
| `WriteToIceberg` | MERGE upsert enriched data into `market_data` Iceberg table via awswrangler |
| `TableMaintenance` | OPTIMIZE (BIN_PACK) on all Iceberg tables; snapshot expiry via table properties (`write.metadata.previous-versions-max=10`) |
| `TriggerDiscovery` | (Optional) PySR formula discovery on accumulated data |

- **Runtime**: Python 3.12
- **Layers**: `AWSSDKPandas-Python312:22` (managed) + extras layer (yfinance/pyyaml)
- **Schedule**: EventBridge triggers daily at 18:00 UTC
- **Error handling**: Catch blocks with SNS notifications on failure

**Cost Allocation:**
- Tag-based tracking by implementation phase
- Per-service breakdowns (S3, SageMaker, Athena, CloudWatch)

## Prerequisites

1. **AWS SSO Configured**:
   ```powershell
   aws configure sso
   # Profile name: company-aws-profile
   # Account: REDACTED-ACCOUNT-ID
   # Region: eu-west-2
   ```

2. **AWS SSO Login**:
   ```powershell
   aws sso login --profile company-aws-profile
   ```

3. **Terraform Installed**:
   ```powershell
   choco install terraform  # or download from terraform.io
   terraform version        # Should be >= 1.0
   ```

4. **Lambda package zips present locally**: `filemd5()` in `data_pipeline.tf` requires both zip files to exist on disk before `terraform plan`. They are not tracked in git. If missing, download from S3:
   ```powershell
   aws s3 cp s3://bblake-platform-data-lake/lambda-packages/data-pipeline-extras-layer.zip ../lambda-packages/data-pipeline-extras-layer.zip --profile company-aws-profile --region eu-west-2
   # data-pipeline.zip is built by scripts/build_lambda.ps1 and uploaded by the Lambda deploy step
   ```

## Setup Instructions

### 1. Create terraform.tfvars

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your values:

```hcl
# Core Configuration
owner_email        = "your.email@company.com"
s3_bucket_prefix   = "your-unique-prefix"  # e.g., "bblake-trading"

# Cost Monitoring
monthly_budget_usd           = 190.0
sagemaker_monthly_budget_usd = 150.0
athena_monthly_budget_usd    = 30.0

# Optional: Slack Notifications
slack_webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

### 2. Initialize Terraform

```bash
terraform init
```

This downloads AWS provider plugins and initializes backend.

### 3. Plan Infrastructure

```bash
terraform plan
```

Review the plan carefully:
- Should create ~50 resources
- S3 buckets: 4
- Glue tables: 5
- CloudWatch dashboards: 3
- Budgets: 3
- Alarms: 5

### 4. Apply Infrastructure

```bash
terraform apply
```

Type `yes` to confirm. This will:
- Create S3 buckets for formula storage
- Set up Glue catalog with Iceberg tables
- Configure CloudWatch dashboards and alarms
- Enable cost monitoring and budgets

### 5. Verify Deployment

```bash
# Check S3 buckets
aws s3 ls --profile company-aws-profile

# Check Glue database
aws glue get-database \
  --name trading_formulas_db \
  --profile company-aws-profile

# Check CloudWatch dashboards
terraform output cloudwatch_formula_performance_dashboard
```

## Outputs

After `terraform apply`, you'll get:

```hcl
s3_formulas_discovery_bucket  = "your-prefix-formulas-discovery"
s3_formulas_staging_bucket    = "your-prefix-formulas-staging"
s3_formulas_production_bucket = "your-prefix-formulas-production"
s3_data_lake_bucket           = "your-prefix-data-lake"

glue_database_name           = "trading_formulas_db"
glue_formula_lineage_table   = "formula_lineage"

cloudwatch_formula_performance_dashboard = "https://..."
cloudwatch_cost_monitoring_dashboard     = "https://..."

monthly_budget = 190.0
```

Copy these values to your `config/config.company.yaml`:

```yaml
aws:
  s3_formulas_discovery_bucket: "your-prefix-formulas-discovery"
  s3_formulas_staging_bucket: "your-prefix-formulas-staging"
  s3_formulas_production_bucket: "your-prefix-formulas-production"
  s3_data_lake_bucket: "your-prefix-data-lake"
  glue_database: "trading_formulas_db"
```

## Cost Estimates

### Monthly Costs (Company Environment)

| Service | Usage | Cost |
|---------|-------|------|
| **S3 Storage** | 10 GB formulas | $0.23 |
| **S3 Requests** | 10K PUT/GET | $0.05 |
| **SageMaker** | 2 jobs/week @ 2 hours | $30-150 |
| **Athena** | 100 GB scanned/month | $5 |
| **Glue Catalog** | 5 tables | $1 |
| **CloudWatch Logs** | 5 GB ingestion | $2.50 |
| **CloudWatch Dashboards** | 3 dashboards | $9 |
| **Cost Explorer** | API calls | $0.01 |
| **Lambda** | 1K invocations | $0.20 |
| **TOTAL** | | **$105-190/month** |

### Cost Optimization Tips

1. **SageMaker Spot Instances**: Save 70% (not used initially for simplicity)
2. **S3 Lifecycle Policies**: Archive old formulas to Glacier after 90 days
3. **Athena Query Limits**: `athena_data_scanned_gb_limit = 100`
4. **SageMaker Runtime Limits**: `sagemaker_max_runtime_seconds = 10800`
5. **CloudWatch Log Retention**: 30 days for SageMaker, 90 days for trading

## Terraform State Management

**Current Setup**: Local state file (`terraform.tfstate`)

**Production Recommendation**: Remote state in S3

```hcl
terraform {
  backend "s3" {
    bucket  = "your-terraform-state-bucket"
    key     = "trading-system/terraform.tfstate"
    region  = "eu-west-2"
    profile = "company-aws-profile"
    encrypt = true
  }
}
```

## Disaster Recovery

### Backup State File

```bash
cp terraform.tfstate terraform.tfstate.backup
```

### Restore from Backup

```bash
cp terraform.tfstate.backup terraform.tfstate
terraform plan  # Verify state matches reality
```

### Import Existing Resources

If resources created outside Terraform:

```bash
# Example: Import existing S3 bucket
terraform import aws_s3_bucket.formulas_discovery your-bucket-name
```

## Updating Infrastructure

### Modify Variables

Edit `terraform.tfvars`:

```hcl
monthly_budget_usd = 250.0  # Increase budget
```

### Apply Changes

```bash
terraform plan   # Review changes
terraform apply  # Apply changes
```

### Add New Resources

1. Edit `.tf` files (e.g., add new S3 bucket)
2. Run `terraform plan`
3. Run `terraform apply`

## Destroying Infrastructure

**WARNING**: This deletes all AWS resources including S3 buckets with formulas!

```bash
# Preview what will be deleted
terraform plan -destroy

# Destroy everything
terraform destroy
```

To preserve S3 data:

1. Export formulas from S3 before destroying
2. Or add `prevent_destroy` lifecycle:

```hcl
resource "aws_s3_bucket" "formulas_production" {
  # ... existing config ...

  lifecycle {
    prevent_destroy = true
  }
}
```

## Troubleshooting

### Error: "BucketAlreadyExists"

S3 bucket names are globally unique. Change `s3_bucket_prefix` in `terraform.tfvars`:

```hcl
s3_bucket_prefix = "bblake-trading-2024"  # More unique
```

### Error: "AccessDenied" from AWS

```bash
# Re-authenticate SSO
aws sso login --profile company-aws-profile

# Verify credentials
aws sts get-caller-identity --profile company-aws-profile
```

### Error: "ExpiredToken"

AWS SSO tokens expire after 8 hours:

```bash
aws sso login --profile company-aws-profile
```

### Cost Exceeds Budget

Check `cloudwatch_cost_monitoring_dashboard` output URL:

```bash
terraform output cloudwatch_cost_monitoring_dashboard
```

Or query Cost Explorer:

```bash
aws ce get-cost-and-usage \
  --time-period Start=2024-01-01,End=2024-01-31 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --profile company-aws-profile
```

## Implementation Phases

This infrastructure supports all 6 phases of the roadmap:

- **Phase 1**: S3 buckets, Glue database, data pipeline — Step Functions + 5 Lambdas + EventBridge schedule (complete)
- **Phase 2**: SageMaker integration, formula loader
- **Phase 3**: A/B testing infrastructure, staging bucket
- **Phase 4**: Circuit breaker monitoring, alarms
- **Phase 5**: CloudWatch dashboards, Grafana integration
- **Phase 6**: Auto-weighting metrics, performance tracking

See [ROADMAP-PRODUCT.md](../docs/ROADMAP-PRODUCT.md) for detailed implementation plan.

## Security Best Practices

1. **SSO Only**: Never use long-term AWS access keys
2. **Least Privilege**: IAM roles grant minimum necessary permissions
3. **Encryption**: All S3 buckets use AES-256 encryption
4. **Versioning**: S3 versioning enabled for audit trail
5. **Logging**: CloudWatch logs retained for compliance
6. **Secrets**: `slack_webhook_url` marked as sensitive in Terraform

## References

- [AWS Terraform Provider Docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Iceberg Table Format](https://iceberg.apache.org/)
- [AWS Cost Explorer API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/Welcome.html)
- [CloudWatch Alarms Best Practices](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Best_Practice_Recommended_Alarms_AWS_Services.html)
