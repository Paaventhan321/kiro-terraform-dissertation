# Scenario 2 - Condition B - Kiro - S3 Secure
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

resource "aws_s3_bucket" "s2_kiro" {
  bucket_prefix = "kiro-s2-"

  tags = {
    Project  = "dissertation"
    Scenario = "S2-Kiro"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s2_kiro" {
  bucket = aws_s3_bucket.s2_kiro.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "s2_kiro" {
  bucket = aws_s3_bucket.s2_kiro.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "s2_kiro" {
  bucket = aws_s3_bucket.s2_kiro.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

