# Scenario 2 - Condition B - Kiro - S3 Intentionally Misconfigured setup
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
