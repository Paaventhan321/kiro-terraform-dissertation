# Scenario 9 - Condition A - Manual - Multi-Resource
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

# S3 Bucket - No encryption
resource "aws_s3_bucket" "s9_manual" {
  bucket_prefix = "manual-s9-"
  tags = {
    Project  = "dissertation"
    Scenario = "S9-Manual"
  }
}

# Security Group - SSH open
resource "aws_security_group" "s9_manual" {
  name_prefix = "manual-s9-"
  description = "Multi-resource test security group"

  ingress {
    description = "SSH from anywhere"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Manual"
  }
}

# IAM Role - Admin permissions
resource "aws_iam_role" "s9_manual" {
  name_prefix = "manual-s9-"

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
    Scenario = "S9-Manual"
  }
}

resource "aws_iam_role_policy_attachment" "s9_manual" {
  role       = aws_iam_role.s9_manual.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# VPC - No flow logs
resource "aws_vpc" "s9_manual" {
  cidr_block = "10.9.0.0/16"

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Manual"
  }
}