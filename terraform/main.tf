# Scenario 13 - Condition A - Manual - RDS PostgreSQL
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

resource "aws_db_instance" "s13_manual" {
  identifier          = "manual-s13-db"
  engine              = "postgres"
  engine_version      = "15"
  instance_class      = "db.t3.micro"
  allocated_storage   = 20
  username            = "admin"
  password            = "TempPass123!"
  skip_final_snapshot = true
  deletion_protection = false
  storage_encrypted   = true
  backup_retention_period = 7

  tags = {
    Project  = "dissertation"
    Scenario = "S13-Manual"
  }
}