# Scenario 1 - Condition A - Manual - S3 Baseline
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

resource "aws_s3_bucket" "s1_manual" {
  bucket_prefix = "manual-s1-"
  tags = {
    Project  = "dissertation"
    Scenario = "S1-Manual"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s1" {
  bucket = aws_s3_bucket.s1_manual.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "s1" {
  bucket                  = aws_s3_bucket.s1_manual.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}