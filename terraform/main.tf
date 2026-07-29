# Scenario 13 - Condition A - Manual - RDS PostgreSQL (corrected)
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_iam_role" "s13_manual_monitoring" {
  name = "manual-s13-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "monitoring.rds.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S13-Manual"
  }
}

resource "aws_iam_role_policy_attachment" "s13_manual_monitoring_policy" {
  role       = aws_iam_role.s13_manual_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_db_instance" "s13_manual" {
  identifier          = "manual-s13-db"
  engine              = "postgres"
  engine_version      = "15"
  instance_class      = "db.t3.micro"
  allocated_storage   = 20

  
  username = "dbadmin"
  password = "TempPass123!"

  skip_final_snapshot     = true
  storage_encrypted       = true
  backup_retention_period = 7

  # --- Checkov fixes below ---
  deletion_protection                = true   # CKV_AWS_293
  auto_minor_version_upgrade          = true   # CKV_AWS_226
  multi_az                            = true   # CKV_AWS_157 (roughly doubles cost while running)
  performance_insights_enabled        = true   # CKV_AWS_353
  performance_insights_kms_key_id     = null   # uses default AWS-managed key
  iam_database_authentication_enabled = true   # CKV_AWS_161
  copy_tags_to_snapshot                = true  # CKV2_AWS_60

  monitoring_interval = 60                                              # CKV_AWS_118
  monitoring_role_arn  = aws_iam_role.s13_manual_monitoring.arn

  # CKV_AWS_129 + CKV2_AWS_30: enable logging, including Postgres query logging
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = {
    Project  = "dissertation"
    Scenario = "S13-Manual"
  }
}