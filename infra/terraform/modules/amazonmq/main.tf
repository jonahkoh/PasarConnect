# =============================================================================
# Amazon MQ — Managed RabbitMQ broker
# Single-instance (SINGLE_INSTANCE) for dev/competition cost control.
# Production should use CLUSTER_MULTI_AZ.
# TLS enforced on AMQPS (port 5671) — plaintext AMQP 5672 is disabled.
# =============================================================================

locals {
  name = "${var.project}-${var.environment}"
}

resource "aws_mq_broker" "main" {
  broker_name        = "${local.name}-rabbitmq"
  engine_type        = "RabbitMQ"
  engine_version     = "3.13"
  host_instance_type = var.mq_instance_type

  # SINGLE_INSTANCE is cheapest — change to CLUSTER_MULTI_AZ for HA.
  deployment_mode    = "SINGLE_INSTANCE"

  # Place the broker in a private subnet — not publicly accessible.
  subnet_ids         = [var.private_subnet_ids[0]]
  security_groups    = [var.data_plane_sg_id]
  publicly_accessible = false

  user {
    username = var.mq_username
    password = var.mq_password
  }

  # Enforce TLS — only AMQPS (5671) is exposed; plain AMQP (5672) is blocked.
  encryption_options {
    use_aws_owned_key = true
  }

  logs {
    general = true   # Ships broker logs to CloudWatch Logs.
  }

  maintenance_window_start_time {
    day_of_week = "SUNDAY"
    time_of_day = "04:00"
    time_zone   = "UTC"
  }

  tags = { Name = "${local.name}-rabbitmq" }
}
