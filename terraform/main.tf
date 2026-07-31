# Scenario 14 - Condition A - Manual - IAM with Mistakes
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

resource "aws_iam_role_policy_attachment" "s14_manual" {
  role       = aws_iam_role.s14_manual.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
}


resource "aws_iam_role_policy_attachment" "s14_manual_lambda" {
  role       = aws_iam_role.s14_manual.name
  policy_arn = "arn:aws:iam::aws:policy/AWSLambda_FullAccess"
}