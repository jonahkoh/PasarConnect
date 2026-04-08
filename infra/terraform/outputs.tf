# =============================================================================
# Root outputs — use these to configure kubectl, ArgoCD, and app secrets
# =============================================================================

# ── EKS ───────────────────────────────────────────────────────────────────────
output "eks_cluster_name" {
  description = "EKS cluster name — pass to aws eks update-kubeconfig."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "eks_oidc_issuer" {
  description = "OIDC issuer URL — needed for additional IRSA roles."
  value       = module.eks.cluster_oidc_issuer_url
}

output "nth_sqs_queue_url" {
  description = "SQS queue URL for the AWS Node Termination Handler Helm chart."
  value       = module.eks.nth_sqs_queue_url
}

output "kms_key_arn" {
  description = "KMS key ARN used for etcd secret encryption."
  value       = module.eks.kms_key_arn
}

# ── Networking ────────────────────────────────────────────────────────────────
output "vpc_id" {
  description = "VPC ID."
  value       = module.vpc.vpc_id
}

output "nat_gateway_ip" {
  description = "NAT Gateway EIP — whitelist this IP in external APIs (Stripe, OutSystems)."
  value       = module.vpc.nat_gateway_ip
}

# ── RDS ───────────────────────────────────────────────────────────────────────
output "rds_endpoint" {
  description = "RDS PostgreSQL host — use this in Kubernetes Secrets."
  value       = module.rds.rds_endpoint
}

output "rds_port" {
  value = module.rds.rds_port
}

# ── DocumentDB ────────────────────────────────────────────────────────────────
output "docdb_endpoint" {
  description = "DocumentDB cluster endpoint — use with the Mongoose connection URI shim."
  value       = module.documentdb.docdb_endpoint
}

output "docdb_port" {
  value = module.documentdb.docdb_port
}

# ── Amazon MQ ─────────────────────────────────────────────────────────────────
output "mq_amqps_endpoint" {
  description = "Amazon MQ AMQPS endpoint — use this in RABBITMQ_URL secrets."
  value       = module.amazonmq.mq_amqps_endpoint
}

# ── S3 ────────────────────────────────────────────────────────────────────────
output "media_bucket_name" {
  value = module.s3.bucket_name
}

# ── IRSA ──────────────────────────────────────────────────────────────────────
output "media_service_role_arn" {
  description = "IAM role ARN to annotate the media-service Kubernetes ServiceAccount."
  value       = module.irsa.media_service_role_arn
}

output "fluent_bit_role_arn" {
  description = "IAM role ARN for the aws-for-fluent-bit DaemonSet ServiceAccount."
  value       = module.irsa.fluent_bit_role_arn
}
