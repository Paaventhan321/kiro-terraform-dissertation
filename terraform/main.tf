# Scenario 9 - Condition B - Kiro - Multi-Resource Connected
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

resource "aws_vpc" "s9_kiro" {
  cidr_block           = "10.9.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
    Name     = "kiro-s9-vpc"
  }
}

resource "aws_subnet" "s9_kiro_public" {
  vpc_id                  = aws_vpc.s9_kiro.id
  cidr_block              = "10.9.1.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
    Name     = "kiro-s9-public-subnet"
  }
}

resource "aws_internet_gateway" "s9_kiro" {
  vpc_id = aws_vpc.s9_kiro.id

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
    Name     = "kiro-s9-igw"
  }
}

resource "aws_route_table" "s9_kiro_public" {
  vpc_id = aws_vpc.s9_kiro.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.s9_kiro.id
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
    Name     = "kiro-s9-public-rt"
  }
}

resource "aws_route_table_association" "s9_kiro_public" {
  subnet_id      = aws_subnet.s9_kiro_public.id
  route_table_id = aws_route_table.s9_kiro_public.id
}

# ── Security Group (HTTP only) ────────────────────────────────────────────────

resource "aws_security_group" "s9_kiro_web" {
  name        = "kiro-s9-web-sg"
  description = "Security group for web server - HTTP only"
  vpc_id      = aws_vpc.s9_kiro.id

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

# ── S3 Bucket ─────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "s9_kiro" {
  bucket_prefix = "kiro-s9-"

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s9_kiro" {
  bucket = aws_s3_bucket.s9_kiro.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "s9_kiro" {
  bucket                  = aws_s3_bucket.s9_kiro.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── IAM Role for EC2 (S3 read + CloudWatch Logs) ──────────────────────────────

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

resource "aws_iam_role_policy" "s9_kiro_s3_access" {
  name = "kiro-s9-s3-access-policy"
  role = aws_iam_role.s9_kiro_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3BucketAccess"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.s9_kiro.arn,
          "${aws_s3_bucket.s9_kiro.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "s9_kiro_cw_logs" {
  role       = aws_iam_role.s9_kiro_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

resource "aws_iam_instance_profile" "s9_kiro" {
  name = "kiro-s9-ec2-instance-profile"
  role = aws_iam_role.s9_kiro_ec2.name

  tags = {
    Project  = "dissertation"
    Scenario = "S9-Kiro"
  }
}
