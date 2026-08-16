# Scenario 5 - Condition B - Kiro - RDS Intentionally Misconfigured rerun
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

resource "aws_db_instance" "s5_kiro" {
  identifier        = "kiro-s5-mysql"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = "db.t3.micro"
  allocated_storage = 20

  db_name  = "dissertation"
  username = "admin"
  password = "changeme123"

  publicly_accessible = true
  storage_encrypted   = false
  deletion_protection = false
  skip_final_snapshot = true

  tags = {
    Project  = "dissertation"
    Scenario = "S5-Kiro"
  }
}
