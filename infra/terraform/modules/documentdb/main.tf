# =============================================================================
# Amazon DocumentDB — MongoDB-compatible cluster
# Single-instance cluster (dev/competition cost control).
# TLS enforced; Mongoose connection string shim documented below.
#
# MONGOOSE CONNECTION URI FORMAT (add this to your auditor service .env):
#   mongodb://<user>:<pass>@<cluster-endpoint>:27017/pasarconnect_audit
#     ?tls=true
#     &tlsCAFile=/app/certs/rds-combined-ca-bundle.pem
#     &retryWrites=false
#     &directConnection=false
#
# NOTE: Download the CA bundle from AWS and mount it into the container:
#   curl -o rds-combined-ca-bundle.pem \
#     https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
# =============================================================================

locals {
  name = "${var.project}-${var.environment}"
}

# ── Subnet Group ─────────────────────────────────────────────────────────────

resource "aws_docdb_subnet_group" "main" {
  name        = "${local.name}-docdb-subnet-group"
  description = "Private subnets for PasarConnect DocumentDB cluster."
  subnet_ids  = var.private_subnet_ids

  tags = { Name = "${local.name}-docdb-subnet-group" }
}

# ── Cluster Parameter Group ───────────────────────────────────────────────────

resource "aws_docdb_cluster_parameter_group" "main" {
  family      = "docdb5.0"
  name        = "${local.name}-docdb-params"
  description = "PasarConnect DocumentDB 5.0 parameters."

  # Enforce TLS on all connections.
  parameter {
    name  = "tls"
    value = "enabled"
  }

  tags = { Name = "${local.name}-docdb-params" }
}

# ── DocumentDB Cluster ────────────────────────────────────────────────────────

resource "aws_docdb_cluster" "main" {
  cluster_identifier              = "${local.name}-docdb"
  engine                          = "docdb"
  engine_version                  = "5.0.0"
  master_username                 = var.docdb_master_username
  master_password                 = var.docdb_master_password
  db_subnet_group_name            = aws_docdb_subnet_group.main.name
  vpc_security_group_ids          = [var.data_plane_sg_id]
  db_cluster_parameter_group_name = aws_docdb_cluster_parameter_group.main.name

  storage_encrypted               = true   # Encryption at rest.
  backup_retention_period         = 7
  preferred_backup_window         = "03:00-04:00"
  preferred_maintenance_window    = "sun:04:00-sun:05:00"

  skip_final_snapshot             = true    # Set to false before production.

  tags = { Name = "${local.name}-docdb" }
}

# ── Single Cluster Instance (dev/competition sizing) ──────────────────────────

resource "aws_docdb_cluster_instance" "main" {
  identifier         = "${local.name}-docdb-0"
  cluster_identifier = aws_docdb_cluster.main.id
  instance_class     = var.docdb_instance_class

  tags = { Name = "${local.name}-docdb-0" }
}
