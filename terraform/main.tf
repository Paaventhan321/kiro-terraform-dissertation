# Scenario 4 - Condition A - Manual - EC2 Secure (reference/simulated baseline)
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

# Manually written - engineer attached AdministratorAccess for convenience
# during setup, intending to narrow it down later (a common real-world habit)
resource "aws_iam_role" "s4_manual_ec2" {
  name = "manual-s4-ec2-role"

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
    Scenario = "S4-Manual"
  }
}

resource "aws_iam_role_policy_attachment" "s4_manual_admin" {
  role       = aws_iam_role.s4_manual_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_iam_instance_profile" "s4_manual" {
  name = "manual-s4-ec2-instance-profile"
  role = aws_iam_role.s4_manual_ec2.name

  tags = {
    Project  = "dissertation"
    Scenario = "S4-Manual"
  }
}

resource "aws_instance" "s4_manual" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = "t2.micro"
  iam_instance_profile        = aws_iam_instance_profile.s4_manual.name
  associate_public_ip_address = true

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
  }

  tags = {
    Project  = "dissertation"
    Scenario = "S4-Manual"
  }
}
