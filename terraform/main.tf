# Scenario 13 - Condition C - Kiro with repair - RDS PostgreSQL Secure
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

resource "aws_db_instance" "s13_kiro" {
  identifier        = "kiro-s13-postgres"
  engine            = "postgres"
  engine_version    = "16.3"
  instance_class    = "db.t3.micro"
  allocated_storage = 20

  db_name  = "dissertation"
  username = "dbadmin"
  password = "changeme123"

  publicly_accessible = false
  storage_encrypted   = true
  deletion_protection = true
  skip_final_snapshot = false
  final_snapshot_identifier = "kiro-s13-postgres-final-snapshot"

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:00-mon:05:00"

  auto_minor_version_upgrade = true

  tags = {
    Project  = "dissertation"
    Scenario = "S13-Kiro"
  }
}

