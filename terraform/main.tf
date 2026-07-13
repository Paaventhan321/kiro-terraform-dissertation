# Scenario 10 - Condition A - Manual step- Valid Syntax Baseline
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

resource "aws_s3_bucket" "s10_manual" {
  bucket_prefix = "manual-s10-"

  tags = {
    Project  = "dissertation"
    Scenario = "S10-Manual"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s10_manual" {
  bucket = aws_s3_bucket.s10_manual.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "s10_manual" {
  bucket                  = aws_s3_bucket.s10_manual.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}