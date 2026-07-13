# Scenario 6 - Condition A - Manual - IAM Admin
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

resource "aws_iam_role" "s6_manual" {
  name_prefix = "manual-s6-"
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
    Scenario = "S6-Manual"
  }
}

resource "aws_iam_role_policy_attachment" "s6_manual" {
  role       = aws_iam_role.s6_manual.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
  
}

resource "aws_iam_policy" "s6_wildcard" {
  name_prefix = "manual-s6-policy-"
  description = "Overly permissive policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
      # Human mistake 4: Wildcard action and resource
    }]
  })
}