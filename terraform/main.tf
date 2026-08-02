# Scenario 18 - Condition B - Kiro - Database Security Group Least Privilege
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

resource "aws_security_group" "s18_kiro_db" {
  name        = "kiro-s18-db-sg"
  description = "Security group for MySQL database - app subnet access only"

  ingress {
    description = "MySQL from application subnet only"
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["10.0.1.0/24"]
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
    Scenario = "S18-Kiro"
  }
}
