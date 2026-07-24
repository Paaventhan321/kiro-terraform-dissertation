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
  name = "kiro-s7-lambda-role-v2"

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

resource "aws_iam_role_policy_attachment" "s7_kiro_basic_exec" {
  role       = aws_iam_role.s7_kiro_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "archive_file" "s7_kiro_lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda_function.py"
  output_path = "${path.module}/lambda_function.zip"
}

resource "aws_lambda_function" "s7_kiro" {
  function_name = "kiro-s7-lambda"
  role          = aws_iam_role.s7_kiro_lambda.arn
  handler       = "lambda_function.handler"
  runtime       = "python3.12"
  filename      = data.archive_file.s7_kiro_lambda_zip.output_path

  
  environment {
    variables = {
      AWS_ACCESS_KEY_ID     = "AKIAABCDEFGHIJKLMNOP"
      AWS_SECRET_ACCESS_KEY = "hardcoded-secret-value-example"
    }
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S7-Kiro"
  }
}

