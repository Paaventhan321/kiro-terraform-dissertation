# Scenario 16 - Condition A - Manual - VPC Private Architecture
# Human engineer created basic VPC but made several security oversights
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

# Human correctly created VPC
resource "aws_vpc" "s16_manual" {
  cidr_block           = "10.16.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Manual"
  }
}

# Human mistake 1:
# Added public IP to private subnet
# Should be false for private subnet
resource "aws_subnet" "s16_manual_public" {
  vpc_id                  = aws_vpc.s16_manual.id
  cidr_block              = "10.16.1.0/24"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Manual-Public"
  }
}

# Human mistake 2:
# Also enabled public IP on private subnet
# This completely defeats the purpose
resource "aws_subnet" "s16_manual_private" {
  vpc_id                  = aws_vpc.s16_manual.id
  cidr_block              = "10.16.2.0/24"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Manual-Private"
  }
}

# Human added internet gateway correctly
resource "aws_internet_gateway" "s16_manual" {
  vpc_id = aws_vpc.s16_manual.id

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Manual-IGW"
  }
}

