# Scenario 6 - Condition B - Kiro - IAM Intentionally Misconfigured
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

resource "aws_iam_role" "s6_kiro_ec2" {
  name_prefix = "kiro-s6-"

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

resource "aws_iam_role_policy_attachment" "s6_kiro_admin" {
  role       = aws_iam_role.s6_kiro_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_instance_profile" "s6_kiro" {
  name_prefix = "kiro-s6-profile-"
  role = aws_iam_role.s6_kiro_ec2.name

  tags = {
    Project  = "dissertation"
    Scenario = "S6-Kiro"
  }
}
