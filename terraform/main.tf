# Scenario 7 - Condition B - Kiro - Lambda Intentionally Misconfigured
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

resource "aws_iam_role" "s7_kiro_lambda" {
  name = "kiro-s7-lambda-role"

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
    Scenario = "S7-Kiro"
  }
}

resource "aws_iam_role_policy_attachment" "s7_kiro_lambda_basic" {
  role       = aws_iam_role.s7_kiro_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "s7_kiro" {
  function_name = "kiro-s7-lambda"
  role          = aws_iam_role.s7_kiro_lambda.arn
  runtime       = "python3.11"
  handler       = "lambda_function.lambda_handler"
  filename      = "lambda_function.zip"

  environment {
    variables = {
      APP_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
      APP_SECRET_KEY = "wJalrXUtnFEMI12345KEY"
      DB_PASSWORD    = "SuperSecret123!"
      API_TOKEN      = "hardcoded-secret-token-12345"
    }
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S7-Kiro"
  }
}
