# Scenario 6 - Condition C - Kiro with repair - IAM Admin
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

resource "aws_iam_role" "s6_kiro" {
  name_prefix = "kiro-s6-"
  description = "Dissertation test role with admin access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S6-Kiro"
  }
}

resource "aws_iam_role_policy_attachment" "s6_kiro" {
  role       = aws_iam_role.s6_kiro.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}