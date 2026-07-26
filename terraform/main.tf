# Scenario 6 - Condition B - Kiro - IAM Least Privilege
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

# ── IAM Role ──────────────────────────────────────────────────────────────────

resource "aws_iam_role" "s6_kiro_ec2" {
  name = "kiro-s6-ec2-role-v3"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S6-Kiro"
  }
}

# S3 read-only access
resource "aws_iam_role_policy_attachment" "s6_kiro_s3_read" {
  role       = aws_iam_role.s6_kiro_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

# CloudWatch Logs write access
resource "aws_iam_role_policy_attachment" "s6_kiro_cw_logs" {
  role       = aws_iam_role.s6_kiro_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

# ── Instance Profile ──────────────────────────────────────────────────────────

resource "aws_iam_instance_profile" "s6_kiro" {
  name = "kiro-s6-ec2-instance-profile-v3"
  role = aws_iam_role.s6_kiro_ec2.name

  tags = {
    Project  = "dissertation"
    Scenario = "S6-Kiro"
  }
}

