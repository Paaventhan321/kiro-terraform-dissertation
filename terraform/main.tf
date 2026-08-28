# Scenario 16 - Condition B - Kiro - VPC Production with Private DB Subnet
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

# ── VPC ───────────────────────────────────────────────────────────────────────

resource "aws_vpc" "s16_kiro" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-vpc"
  }
}

# ── Public Subnets (application tier) ────────────────────────────────────────

resource "aws_subnet" "s16_kiro_public_a" {
  vpc_id                  = aws_vpc.s16_kiro.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-public-a"
    Tier     = "public"
  }
}

resource "aws_subnet" "s16_kiro_public_b" {
  vpc_id                  = aws_vpc.s16_kiro.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = "us-east-1b"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-public-b"
    Tier     = "public"
  }
}

# ── Private Subnets (database tier — no internet access) ─────────────────────

resource "aws_subnet" "s16_kiro_private_a" {
  vpc_id                  = aws_vpc.s16_kiro.id
  cidr_block              = "10.0.11.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = false

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-private-a"
    Tier     = "database"
  }
}

resource "aws_subnet" "s16_kiro_private_b" {
  vpc_id                  = aws_vpc.s16_kiro.id
  cidr_block              = "10.0.12.0/24"
  availability_zone       = "us-east-1b"
  map_public_ip_on_launch = false

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-private-b"
    Tier     = "database"
  }
}

# ── Internet Gateway (public tier only) ───────────────────────────────────────

resource "aws_internet_gateway" "s16_kiro" {
  vpc_id = aws_vpc.s16_kiro.id

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-igw"
  }
}

# ── Public Route Table ────────────────────────────────────────────────────────

resource "aws_route_table" "s16_kiro_public" {
  vpc_id = aws_vpc.s16_kiro.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.s16_kiro.id
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-public-rt"
  }
}

resource "aws_route_table_association" "s16_kiro_public_a" {
  subnet_id      = aws_subnet.s16_kiro_public_a.id
  route_table_id = aws_route_table.s16_kiro_public.id
}

resource "aws_route_table_association" "s16_kiro_public_b" {
  subnet_id      = aws_subnet.s16_kiro_public_b.id
  route_table_id = aws_route_table.s16_kiro_public.id
}

# ── Private Route Table (no internet route) ───────────────────────────────────

resource "aws_route_table" "s16_kiro_private" {
  vpc_id = aws_vpc.s16_kiro.id

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-private-rt"
  }
}

resource "aws_route_table_association" "s16_kiro_private_a" {
  subnet_id      = aws_subnet.s16_kiro_private_a.id
  route_table_id = aws_route_table.s16_kiro_private.id
}

resource "aws_route_table_association" "s16_kiro_private_b" {
  subnet_id      = aws_subnet.s16_kiro_private_b.id
  route_table_id = aws_route_table.s16_kiro_private.id
}

# ── DB Subnet Group ───────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "s16_kiro" {
  name       = "kiro-s16-db-subnet-group"
  subnet_ids = [aws_subnet.s16_kiro_private_a.id, aws_subnet.s16_kiro_private_b.id]

  tags = {
    Project  = "dissertation"
    Scenario = "S16-Kiro"
    Name     = "kiro-s16-db-subnet-group"
  }
}
