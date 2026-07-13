# Scenario 7 - Condition A - Manual - Lambda Hardcoded Credentials
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

resource "aws_iam_role" "s7_manual_lambda" {
  name_prefix = "manual-s7-lambda-"

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
    Scenario = "S7-Manual"
  }
}

resource "aws_lambda_function" "s7_manual" {
  filename      = "lambda_function.zip"
  function_name = "manual-s7-lambda"
  role          = aws_iam_role.s7_manual_lambda.arn
  handler       = "index.handler"
  runtime       = "python3.11"

  environment {
  variables = {
    APP_ACCESS_KEY    = "AKIAIOSFODNN7EXAMPLE"
    APP_SECRET_KEY    = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    DB_PASSWORD       = "SuperSecret123!"
    API_TOKEN         = "hardcoded-secret-token-12345"
  }
}

  tags = {
    Project  = "dissertation"
    Scenario = "S7-Manual"
  }
}