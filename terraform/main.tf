provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "s1_manual" {
  bucket = "dissertation-s1-manual-bucket"

  tags = {
    Project  = "dissertation"
    Scenario = "S1-Kiro"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s1_manual" {
  bucket = aws_s3_bucket.s1_manual.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "s1_manual" {
  bucket = aws_s3_bucket.s1_manual.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}