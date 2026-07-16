# Scenario 11 - Condition B - Kiro - VPC with NAT Gateway and Private EC2
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

# ── VPC ──────────────────────────────────────────────────────────────────────

resource "aws_vpc" "s11_kiro" {
  cidr_block = "10.0.0.0/16"

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-vpc"
  }
}

# ── Subnets ───────────────────────────────────────────────────────────────────

resource "aws_subnet" "s11_kiro_public" {
  vpc_id                  = aws_vpc.s11_kiro.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-public-subnet"
  }
}

resource "aws_subnet" "s11_kiro_private" {
  vpc_id                  = aws_vpc.s11_kiro.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = "us-east-1b"
  map_public_ip_on_launch = false

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-private-subnet"
  }
}

# ── Internet Gateway ──────────────────────────────────────────────────────────

resource "aws_internet_gateway" "s11_kiro" {
  vpc_id = aws_vpc.s11_kiro.id

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-igw"
  }
}

# ── NAT Gateway (requires an Elastic IP) ─────────────────────────────────────

resource "aws_eip" "s11_kiro_nat" {
  domain = "vpc"

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-nat-eip"
  }
}

resource "aws_nat_gateway" "s11_kiro" {
  allocation_id = aws_eip.s11_kiro_nat.id
  subnet_id     = aws_subnet.s11_kiro_public.id

  depends_on = [aws_internet_gateway.s11_kiro]

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-nat-gw"
  }
}

# ── Route Tables ──────────────────────────────────────────────────────────────

# Public route table — default route via Internet Gateway
resource "aws_route_table" "s11_kiro_public" {
  vpc_id = aws_vpc.s11_kiro.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.s11_kiro.id
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-public-rt"
  }
}

resource "aws_route_table_association" "s11_kiro_public" {
  subnet_id      = aws_subnet.s11_kiro_public.id
  route_table_id = aws_route_table.s11_kiro_public.id
}

# Private route table — default route via NAT Gateway
resource "aws_route_table" "s11_kiro_private" {
  vpc_id = aws_vpc.s11_kiro.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.s11_kiro.id
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-private-rt"
  }
}

resource "aws_route_table_association" "s11_kiro_private" {
  subnet_id      = aws_subnet.s11_kiro_private.id
  route_table_id = aws_route_table.s11_kiro_private.id
}

# ── AMI (Amazon Linux 2023) ───────────────────────────────────────────────────

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── EC2 Instance in Private Subnet ────────────────────────────────────────────

resource "aws_instance" "s11_kiro_private" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = "t2.micro"
  subnet_id                   = aws_subnet.s11_kiro_private.id
  associate_public_ip_address = false

  tags = {
    Project  = "dissertation"
    Scenario = "S11-Kiro"
    Name     = "kiro-s11-private-ec2"
  }
}
