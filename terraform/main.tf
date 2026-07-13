# Scenario 9 - Condition B - Kiro - Multi-Resource Intentionally Misconfigured
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

# S3 Bucket - no encryption
resource "aws_s3_bucket" "s9_kiro" {
  bucket_prefix = "kiro-s9-"

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
  }
}

# Security Group - SSH and HTTP open to the world
resource "aws_security_group" "s9_kiro_web" {
  name        = "kiro-s9-web-sg"
  description = "Security group for web server"

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
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
  }
}

# IAM Role - AdministratorAccess
resource "aws_iam_role" "s9_kiro_ec2" {
  name = "kiro-s9-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
  }
}

resource "aws_iam_role_policy_attachment" "s9_kiro_admin" {
  role       = aws_iam_role.s9_kiro_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# VPC - no flow logs
resource "aws_vpc" "s9_kiro" {
  cidr_block = "10.9.0.0/16"

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
  }
}
