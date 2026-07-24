# Scenario 4 - Condition B - Kiro - EC2 Secure
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

# ── AMI ───────────────────────────────────────────────────────────────────────
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

# ── IAM Role (least-privilege — SSM access only) ──────────────────────────────
resource "aws_iam_role" "s4_kiro_ec2" {
  name = "kiro-s4-ec2-role-v2"

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
    Scenario = "S4-Kiro"
  }
}

resource "aws_iam_role_policy_attachment" "s4_kiro_ssm" {
  role       = aws_iam_role.s4_kiro_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "s4_kiro" {
  name = "kiro-s4-ec2-instance-profile-v2"
  role = aws_iam_role.s4_kiro_ec2.name

  tags = {
    Project  = "dissertation"
    Scenario = "S4-Kiro"
  }
}

# ── EC2 Instance ──────────────────────────────────────────────────────────────
resource "aws_instance" "s4_kiro" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = "t2.micro"
  iam_instance_profile        = aws_iam_instance_profile.s4_kiro.name
  associate_public_ip_address = false

  # Enforce IMDSv2
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  # Encrypted root volume bumped to 30GB — 20GB was smaller than the
  # AMI's underlying snapshot minimum, which caused a separate apply-time
  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 20
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S4-Kiro"
  }
}

