# Scenario 8 - Condition A - Manual - VPC No Flow Logs
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

resource "aws_vpc" "s8_manual" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Manual"
  }
}

resource "aws_subnet" "s8_manual_public" {
  vpc_id                  = aws_vpc.s8_manual.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Manual-Public"
  }
}

resource "aws_subnet" "s8_manual_private" {
  vpc_id     = aws_vpc.s8_manual.id
  cidr_block = "10.0.2.0/24"

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Manual-Private"
  }
}

resource "aws_internet_gateway" "s8_manual" {
  vpc_id = aws_vpc.s8_manual.id

  tags = {
    Project  = "dissertation"
    Scenario = "S8-Manual-IGW"
  }
}

# Human forgot to add VPC flow logs
# Human forgot to disable public IP auto-assignment