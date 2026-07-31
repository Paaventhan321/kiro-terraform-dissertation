# Scenario 14 - Condition A - Manual - IAM Least Privilege
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

resource "aws_iam_role" "s14_manual" {
  name_prefix = "manual-s14-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S14-Manual"
  }
}

resource "aws_iam_policy" "s14_manual" {
  name_prefix = "manual-s14-policy-"
  description = "DynamoDB read only policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan"
      ]
      Resource = "arn:aws:dynamodb:us-east-1:*:table/my-table"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "s14_manual" {
  role       = aws_iam_role.s14_manual.name
  policy_arn = aws_iam_policy.s14_manual.arn
}
