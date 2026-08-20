# Scenario 11 - Condition B - Kiro - S3 Audit Log Storage
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

resource "aws_s3_bucket" "s11_kiro_audit" {
  bucket_prefix = "kiro-s11-audit-"

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
  }
}

# Encryption at rest
resource "aws_s3_bucket_server_side_encryption_configuration" "s11_kiro_audit" {
  bucket = aws_s3_bucket.s11_kiro_audit.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning for audit integrity
resource "aws_s3_bucket_versioning" "s11_kiro_audit" {
  bucket = aws_s3_bucket.s11_kiro_audit.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "s11_kiro_audit" {
  bucket = aws_s3_bucket.s11_kiro_audit.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle policy for long-term retention
resource "aws_s3_bucket_lifecycle_configuration" "s11_kiro_audit" {
  bucket = aws_s3_bucket.s11_kiro_audit.id

  rule {
    id     = "audit-log-retention"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }

    transition {
      days          = 1095
      storage_class = "DEEP_ARCHIVE"
    }

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_transition {
      noncurrent_days = 90
      storage_class   = "GLACIER"
    }
  }
}

