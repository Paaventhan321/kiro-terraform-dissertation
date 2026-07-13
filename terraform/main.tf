# Scenario 5 - Condition B - Kiro - RDS Public
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
  identifier        = "kiro-s5-db"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  username          = "admin"
  password          = "TempPass123!"

  publicly_accessible = true
  skip_final_snapshot = true
  deletion_protection = false
  storage_encrypted   = false

  tags = {
    Project  = "dissertation"
    Scenario = "S5-Kiro"
  }
}