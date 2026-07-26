# Scenario 6 - Condition A - Manual - IAM Role 
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

resource "aws_iam_role" "s6_manual_ec2" {
  name = "manual-s6-ec2-role"

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
    Scenario = "S6-Manual"
  }
}


resource "aws_iam_role_policy_attachment" "s6_manual_s3" {
  role       = aws_iam_role.s6_manual_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "s6_manual_cw_logs" {
  role       = aws_iam_role.s6_manual_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchFullAccess"
}

resource "aws_iam_instance_profile" "s6_manual" {
  name = "manual-s6-ec2-instance-profile"
  role = aws_iam_role.s6_manual_ec2.name

  tags = {
    Project  = "dissertation"
    Scenario = "S6-Manual"
  }
}
