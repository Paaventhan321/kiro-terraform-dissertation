# Scenario 8 - Condition B - Kiro - VPC Intentionally Misconfigured
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

resource "aws_vpc" "s8_kiro" {
  cidr_block = "10.0.0.0/16"

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Kiro"
  }
}

resource "aws_subnet" "s8_kiro_public" {
  vpc_id            = aws_vpc.s8_kiro.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1a"

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Kiro"
    Type     = "public"
  }
}

resource "aws_subnet" "s8_kiro_private" {
  vpc_id            = aws_vpc.s8_kiro.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "us-east-1b"

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Kiro"
    Type     = "private"
  }
}

resource "aws_internet_gateway" "s8_kiro" {
  vpc_id = aws_vpc.s8_kiro.id

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Kiro"
  }
}
