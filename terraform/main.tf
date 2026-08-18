# Scenario 10 - Condition B - Kiro - S3 Minimal
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

resource "aws_s3_bucket" "s10_kiro" {
  bucket_prefix = "kiro-s10-"

  tags = {
    Project  = "dissertation"
    Scenario = "S10-Kiro"
  }
}
