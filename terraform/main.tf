# Scenario 14 - Condition B - Kiro - Lambda IAM Least Privilege DynamoDB
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

data "aws_caller_identity" "current" {}

# ── IAM Role ──────────────────────────────────────────────────────────────────

resource "aws_iam_role" "s14_kiro_lambda" {
  name = "kiro-s14-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S14-Kiro"
  }
}

# Basic Lambda execution (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "s14_kiro_lambda_basic" {
  role       = aws_iam_role.s14_kiro_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Least-privilege inline policy — read-only on one specific DynamoDB table
resource "aws_iam_role_policy" "s14_kiro_dynamodb_read" {
  name = "kiro-s14-dynamodb-read-policy"
  role = aws_iam_role.s14_kiro_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBReadOnly"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:DescribeTable"
        ]
        Resource = "arn:aws:dynamodb:us-east-1:${data.aws_caller_identity.current.account_id}:table/dissertation-data-table"
      }
    ]
  })
}
