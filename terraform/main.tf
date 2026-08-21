# Scenario 19 - Condition B - Kiro - CloudTrail Without Security Controls
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

resource "aws_s3_bucket" "s19_trail_bucket" {
  bucket_prefix = "kiro-s19-trail-"
  force_destroy = true

  tags = {
    Project  = "dissertation"
    Scenario = "S19-Kiro"
  }
}

resource "aws_s3_bucket_public_access_block" "s19_trail" {
  bucket                  = aws_s3_bucket.s19_trail_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Missing: bucket policy allowing CloudTrail to write
# Missing: log file validation
# Missing: KMS encryption on trail
# Missing: multi-region trail
resource "aws_cloudtrail" "s19_kiro" {
  name                          = "kiro-s19-trail"
  s3_bucket_name                = aws_s3_bucket.s19_trail_bucket.id
  include_global_service_events = false
  is_multi_region_trail         = false
  enable_log_file_validation    = false

  tags = {
    Project  = "dissertation"
    Scenario = "S19-Kiro"
  }
}

