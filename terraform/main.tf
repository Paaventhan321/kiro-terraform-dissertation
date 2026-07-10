# Scenario 2 - Condition A - Manual - Missing Encryption
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

resource "aws_s3_bucket" "s2_manual" {
  bucket_prefix = "manual-s2-"
  tags = {
    Project  = "dissertation"
    Scenario = "S2-Manual"
  }
}

resource "aws_s3_bucket_public_access_block" "s2_manual" {
  bucket                  = aws_s3_bucket.s2_manual.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Human deliberately forgot encryption
# Human deliberately forgot versioning
# Human deliberately forgot logging
