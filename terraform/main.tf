# Scenario 17 - Condition B - Kiro - S3 Disaster Recovery
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  alias  = "primary"
  region = "us-east-1"
}

provider "aws" {
  alias  = "replica"
  region = "eu-west-1"
}

# ── Primary Bucket (us-east-1) ────────────────────────────────────────────────

resource "aws_s3_bucket" "s17_kiro_primary" {
  provider      = aws.primary
  bucket_prefix = "kiro-s17-primary-"

  object_lock_enabled = true

  tags = {
    Project  = "dissertation"
    Scenario = "S17-Kiro"
    Role     = "primary"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s17_kiro_primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.s17_kiro_primary.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "s17_kiro_primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.s17_kiro_primary.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Object lock — COMPLIANCE mode prevents deletion for 7 years
resource "aws_s3_bucket_object_lock_configuration" "s17_kiro_primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.s17_kiro_primary.id

  rule {
    default_retention {
      mode  = "COMPLIANCE"
      years = 7
    }
  }
}

resource "aws_s3_bucket_public_access_block" "s17_kiro_primary" {
  provider                = aws.primary
  bucket                  = aws_s3_bucket.s17_kiro_primary.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Replica Bucket (eu-west-1) ────────────────────────────────────────────────

resource "aws_s3_bucket" "s17_kiro_replica" {
  provider      = aws.replica
  bucket_prefix = "kiro-s17-replica-"

  tags = {
    Project  = "dissertation"
    Scenario = "S17-Kiro"
    Role     = "replica"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s17_kiro_replica" {
  provider = aws.replica
  bucket   = aws_s3_bucket.s17_kiro_replica.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "s17_kiro_replica" {
  provider = aws.replica
  bucket   = aws_s3_bucket.s17_kiro_replica.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "s17_kiro_replica" {
  provider                = aws.replica
  bucket                  = aws_s3_bucket.s17_kiro_replica.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── IAM Role for Replication ──────────────────────────────────────────────────

resource "aws_iam_role" "s17_kiro_replication" {
  name = "kiro-s17-s3-replication-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S17-Kiro"
  }
}

resource "aws_iam_role_policy" "s17_kiro_replication" {
  name = "kiro-s17-replication-policy"
  role = aws_iam_role.s17_kiro_replication.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetReplicationConfiguration",
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.s17_kiro_primary.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObjectVersionForReplication",
          "s3:GetObjectVersionAcl",
          "s3:GetObjectVersionTagging"
        ]
        Resource = "${aws_s3_bucket.s17_kiro_primary.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ReplicateObject",
          "s3:ReplicateDelete",
          "s3:ReplicateTags"
        ]
        Resource = "${aws_s3_bucket.s17_kiro_replica.arn}/*"
      }
    ]
  })
}

# ── Cross-Region Replication ──────────────────────────────────────────────────

resource "aws_s3_bucket_replication_configuration" "s17_kiro" {
  provider = aws.primary
  bucket   = aws_s3_bucket.s17_kiro_primary.id
  role     = aws_iam_role.s17_kiro_replication.arn

  depends_on = [aws_s3_bucket_versioning.s17_kiro_primary]

  rule {
    id     = "replicate-all"
    status = "Enabled"

    destination {
      bucket        = aws_s3_bucket.s17_kiro_replica.arn
      storage_class = "STANDARD"
    }
  }
}
