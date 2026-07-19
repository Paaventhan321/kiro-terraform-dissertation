# Scenario 1 - Condition C - Kiro - S3 Baseline
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

resource "aws_s3_bucket" "s1_kiro" {
  bucket_prefix = "kiro-s1-"

  tags = {
    Project  = "dissertation"
    Scenario = "S1-Kiro"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s1_kiro" {
  bucket = aws_s3_bucket.s1_kiro.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "s1_kiro" {
  bucket = aws_s3_bucket.s1_kiro.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "s1_kiro" {
  bucket = aws_s3_bucket.s1_kiro.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
