# Scenario 15 - Condition B - Kiro - Lambda with Hardcoded RDS Credentials
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

resource "aws_iam_role" "s15_kiro_lambda" {
  name = "kiro-s15-lambda-role"

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
    Scenario = "S15-Kiro"
  }
}

resource "aws_iam_role_policy_attachment" "s15_kiro_lambda_basic" {
  role       = aws_iam_role.s15_kiro_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ── Lambda Function ───────────────────────────────────────────────────────────

resource "aws_lambda_function" "s15_kiro" {
  function_name = "kiro-s15-lambda"
  role          = aws_iam_role.s15_kiro_lambda.arn
  runtime       = "python3.11"
  handler       = "lambda_function.lambda_handler"
  filename      = "lambda_function.zip"

  environment {
    variables = {
      DB_HOST     = "dissertation-db.cluster-abc123.us-east-1.rds.amazonaws.com"
      DB_PORT     = "3306"
      DB_NAME     = "dissertationdb"
      DB_USERNAME = "admin"
      DB_PASSWORD = "SuperSecret123!"
    }
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S15-Kiro"
  }
}
