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

# ── S3 Bucket with Server-Side Encryption ────────────────────────────────────

resource "aws_s3_bucket" "dissertation" {
  bucket_prefix = "dissertation-"

  tags = {
    Project = "dissertation"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dissertation" {
  bucket = aws_s3_bucket.dissertation.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ── Security Group – HTTP on port 80 ─────────────────────────────────────────

resource "aws_security_group" "dissertation_http" {
  name        = "dissertation-http"
  description = "Allow inbound HTTP traffic on port 80"

  ingress {
    description = "HTTP"
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
    Project = "dissertation"
  }
}

# ── EC2 t2.micro Instance ─────────────────────────────────────────────────────

# Latest Amazon Linux 2023 AMI in us-east-1
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

resource "aws_instance" "dissertation" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = "t2.micro"
  vpc_security_group_ids = [aws_security_group.dissertation_http.id]

  tags = {
    Project = "dissertation"
    Name    = "dissertation-instance"
  }
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "s3_bucket_name" {
  description = "Name of the created S3 bucket"
  value       = aws_s3_bucket.dissertation.id
}

output "security_group_id" {
  description = "ID of the HTTP security group"
  value       = aws_security_group.dissertation_http.id
}

output "ec2_instance_id" {
  description = "ID of the EC2 instance"
  value       = aws_instance.dissertation.id
}

output "ec2_public_ip" {
  description = "Public IP address of the EC2 instance"
  value       = aws_instance.dissertation.public_ip
}
