# DEPRECATED 2026-05-28 -- CD.21
# Self-hosted EC2 runner retired; CI now uses GitHub-hosted runners + OIDC (personal account).
# Retained as an architectural-evolution artefact per CD.21. The work-account root is no longer
# applied; to fully decommission run terraform destroy against the work-account state later.
# The live instance was terminated via AWS CLI on 2026-05-28 (Phase A, Step 4b).

# Self-hosted GitHub Actions runner on EC2 (Decision 68)
# Replaces GitHub-hosted ubuntu-latest to eliminate the 2000 min/month billing cap.
# IAM credentials via instance metadata -- no SSO session needed in CI.

data "aws_ami" "ubuntu_22_04" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_caller_identity" "runner" {}

# Look up existing S3 buckets by name -- avoids pulling main.tf resource definitions
# as apply-time dependencies, which would cause Terraform to attempt recreation.
data "aws_s3_bucket" "runner_agent_logs" {
  bucket = "agent-platform-agent-logs"
}

data "aws_s3_bucket" "runner_data_lake" {
  bucket = "${var.s3_bucket_prefix}-data-lake"
}

resource "aws_security_group" "github_runner" {
  name_prefix = "${var.project_name}-runner-"
  description = "Self-hosted GitHub Actions runner -- egress HTTPS and HTTP"

  lifecycle {
    create_before_destroy = true
  }

  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Port 80 required for apt package repository access (Ubuntu archive, security updates).
  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-runner"
    Purpose = "GitHub Actions self-hosted runner security group"
  }
}

resource "aws_iam_role" "github_runner" {
  name = "${var.project_name}-runner"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-runner"
    Purpose = "IAM role for GitHub Actions self-hosted runner"
  }
}

resource "aws_iam_policy" "github_runner_ci" {
  name        = "${var.project_name}-runner-ci"
  description = "Least-privilege CI access for the self-hosted runner (Decision 68)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # StartQueryExecution scoped to the two CI workgroups -- prevents query execution against any other workgroup.
        Sid    = "AthenaStartQuery"
        Effect = "Allow"
        Action = ["athena:StartQueryExecution"]
        Resource = [
          "arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:workgroup/${var.project_name}-production",
          "arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:workgroup/${var.project_name}-lab"
        ]
      },
      {
        # GetQueryExecution/GetQueryResults/ListWorkGroups/GetWorkGroup do not support workgroup-level resource constraints in IAM.
        Sid    = "AthenaQueryStatus"
        Effect = "Allow"
        Action = [
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:ListWorkGroups",
          "athena:GetWorkGroup"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3ReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "${data.aws_s3_bucket.runner_agent_logs.arn}/*",
          "${data.aws_s3_bucket.runner_data_lake.arn}/athena/*"
        ]
      },
      {
        Sid    = "S3List"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          data.aws_s3_bucket.runner_agent_logs.arn,
          data.aws_s3_bucket.runner_data_lake.arn
        ]
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:table/${var.project_name}-*"
      },
      {
        Sid    = "Glue"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions"
        ]
        Resource = "*"
      },
      {
        # Required: verifier compact() calls delete temporary Parquet files from the tmp/ prefix.
        Sid      = "S3DeleteTmp"
        Effect   = "Allow"
        Action   = ["s3:DeleteObject"]
        Resource = ["${data.aws_s3_bucket.runner_agent_logs.arn}/tmp/*"]
      },
      {
        # Required: Athena verifies the output bucket with GetBucketLocation before executing any query.
        # Grant on both buckets -- data-lake is the Athena workgroup output; agent-logs is used by session_preflight.py.
        Sid    = "S3BucketLocation"
        Effect = "Allow"
        Action = ["s3:GetBucketLocation"]
        Resource = [
          data.aws_s3_bucket.runner_data_lake.arn,
          data.aws_s3_bucket.runner_agent_logs.arn
        ]
      },
      {
        # Required: SchemaIntegrityVerifier and IcebergCompactionVerifier call DeleteTable/CreateTable/UpdateTable
        # during Iceberg OPTIMIZE and VACUUM operations. Three ARNs required: catalog, database, table.
        Sid    = "GlueTableMutations"
        Effect = "Allow"
        Action = ["glue:DeleteTable", "glue:CreateTable", "glue:UpdateTable"]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:database/trading_formulas_db",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:table/trading_formulas_db/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "github_runner_ci" {
  role       = aws_iam_role.github_runner.name
  policy_arn = aws_iam_policy.github_runner_ci.arn
}

resource "aws_iam_instance_profile" "github_runner" {
  name = "${var.project_name}-runner"
  role = aws_iam_role.github_runner.name
}

resource "aws_instance" "github_runner" {
  ami                         = data.aws_ami.ubuntu_22_04.id
  instance_type               = "t3.medium"
  iam_instance_profile        = aws_iam_instance_profile.github_runner.name
  vpc_security_group_ids      = [aws_security_group.github_runner.id]
  associate_public_ip_address = true

  root_block_device {
    volume_size = 20
    volume_type = "gp2"
  }

  user_data = <<EOF
#!/bin/bash
set -e
apt-get update -y
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y git curl unzip python3.12 python3.12-venv python3-pip jq
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
apt-get update -y
apt-get install -y gh
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
# Runner binary registration is intentionally absent: the GitHub registration token
# expires in 60 minutes and cannot be embedded here. See CLAUDE.md runbook for
# the manual registration steps to complete after terraform apply.
mkdir -p /home/ubuntu/actions-runner
chown ubuntu:ubuntu /home/ubuntu/actions-runner
mkdir -p /home/ubuntu/.aws
printf '[profile company-aws-profile]\ncredential_source = Ec2InstanceMetadata\nregion = eu-west-2\n' > /home/ubuntu/.aws/config
chown -R ubuntu:ubuntu /home/ubuntu/.aws
chmod 600 /home/ubuntu/.aws/config
EOF

  tags = {
    Name    = "agent-platform-runner"
    Purpose = "GitHub Actions self-hosted runner"
  }
}
