# =============================================================================
# RDS — Single PostgreSQL instance, 6 logical databases
# IAM database authentication enabled (services use short-lived tokens,
# not static passwords — eliminates the need to rotate credentials).
# PgBouncer (connection pooler) is deployed as a Kubernetes Deployment
# in Batch 3; this module provisions only the RDS infra.
# =============================================================================

locals {
  name = "${var.project}-${var.environment}"
}

# ── Subnet Group ─────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name        = "${local.name}-rds-subnet-group"
  description = "Private subnets for PasarConnect RDS instance."
  subnet_ids  = var.private_subnet_ids

  tags = { Name = "${local.name}-rds-subnet-group" }
}

# ── Parameter Group ───────────────────────────────────────────────────────────
# Forces SSL connections and tunes connection-related settings.

resource "aws_db_parameter_group" "main" {
  name        = "${local.name}-pg16"
  family      = "postgres16"
  description = "PasarConnect PostgreSQL 16 parameter group."

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # Raise max_connections ceiling — PgBouncer will multiplex down to this.
  parameter {
    name         = "max_connections"
    value        = "200"
    apply_method = "pending-reboot"
  }

  tags = { Name = "${local.name}-pg16-params" }
}

# ── RDS Instance ──────────────────────────────────────────────────────────────

resource "aws_db_instance" "main" {
  identifier        = "${local.name}-postgres"
  engine            = "postgres"
  engine_version    = "16.2"
  instance_class    = var.rds_instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true   # Encryption at rest — mandatory.

  db_name  = "postgres"           # Default DB; logical databases created via provisioner below.
  username = var.rds_master_username
  password = var.rds_master_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.data_plane_sg_id]
  parameter_group_name   = aws_db_parameter_group.main.name

  iam_database_authentication_enabled = true   # Enables token-based auth for services via IRSA.

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  deletion_protection = false   # Set to true before going to production.
  skip_final_snapshot = true    # Set to false before going to production.

  multi_az = false   # Single-AZ for competition cost control. Enable for prod.

  tags = { Name = "${local.name}-postgres" }
}

# ── Logical Databases ─────────────────────────────────────────────────────────
# Each microservice gets its own logical database on the single RDS instance.
# The null_resource runs a psql command from the Terraform runner to create them.
# This requires the runner to have network access to RDS (e.g., via a bastion
# or by running Terraform from within the VPC — e.g., a GitHub Actions self-hosted runner).

resource "null_resource" "create_databases" {
  count = length(var.rds_logical_databases)

  triggers = {
    db_name = var.rds_logical_databases[count.index]
  }

  provisioner "local-exec" {
    command = <<-EOT
      PGPASSWORD="${var.rds_master_password}" psql \
        -h ${aws_db_instance.main.address} \
        -U ${var.rds_master_username} \
        -d postgres \
        -c "SELECT 'CREATE DATABASE ${var.rds_logical_databases[count.index]}' \
            WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${var.rds_logical_databases[count.index]}')\gexec"
    EOT
  }

  depends_on = [aws_db_instance.main]
}
