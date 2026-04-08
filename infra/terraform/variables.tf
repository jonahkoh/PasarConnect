# =============================================================================
# Global
# =============================================================================

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-southeast-1"
}

variable "environment" {
  description = "Deployment environment label (dev | staging | prod)."
  type        = string
  default     = "dev"
}

variable "project" {
  description = "Project name prefix used in resource naming."
  type        = string
  default     = "pasarconnect"
}

# =============================================================================
# VPC
# =============================================================================

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of AZs to use. Defaults to 2 for cost optimisation."
  type        = list(string)
  default     = ["ap-southeast-1a", "ap-southeast-1b"]
}

# =============================================================================
# EKS
# =============================================================================

variable "eks_cluster_version" {
  description = "Kubernetes version for the EKS cluster."
  type        = string
  default     = "1.29"
}

variable "on_demand_instance_type" {
  description = "EC2 instance type for the system (On-Demand) node group."
  type        = string
  default     = "t3.medium"
}

variable "spot_instance_types" {
  description = "EC2 instance types for the app (Spot) node group. Multiple types improve Spot availability."
  type        = list(string)
  default     = ["t3.medium", "t3a.medium", "t3.large"]
}

variable "on_demand_desired" {
  type    = number
  default = 2
}

variable "spot_desired" {
  type    = number
  default = 2
}

variable "spot_min" {
  type    = number
  default = 1
}

variable "spot_max" {
  type    = number
  default = 6
}

# =============================================================================
# RDS
# =============================================================================

variable "rds_instance_class" {
  description = "RDS instance class. db.t3.micro qualifies for Free Tier."
  type        = string
  default     = "db.t3.micro"
}

variable "rds_master_username" {
  description = "Master username for the RDS PostgreSQL instance."
  type        = string
  default     = "pasarconnect_admin"
}

variable "rds_master_password" {
  description = "Master password for the RDS PostgreSQL instance. Pass via TF_VAR or Secrets Manager."
  type        = string
  sensitive   = true
}

variable "rds_logical_databases" {
  description = "List of logical database names to create inside the single RDS instance."
  type        = list(string)
  default = [
    "inventory_db",
    "claim_db",
    "payment_db",
    "verification_db",
    "waitlist_db",
    "notification_db",
  ]
}

# =============================================================================
# DocumentDB
# =============================================================================

variable "docdb_instance_class" {
  description = "DocumentDB instance class."
  type        = string
  default     = "db.t3.medium"
}

variable "docdb_master_username" {
  description = "Master username for DocumentDB."
  type        = string
  default     = "pasarconnect_admin"
}

variable "docdb_master_password" {
  description = "Master password for DocumentDB. Pass via TF_VAR or Secrets Manager."
  type        = string
  sensitive   = true
}

# =============================================================================
# Amazon MQ
# =============================================================================

variable "mq_instance_type" {
  description = "Amazon MQ broker instance type."
  type        = string
  default     = "mq.t3.micro"
}

variable "mq_username" {
  description = "RabbitMQ broker username."
  type        = string
  default     = "pasarconnect"
}

variable "mq_password" {
  description = "RabbitMQ broker password. Min 12 chars, must include special character."
  type        = string
  sensitive   = true
}

# =============================================================================
# S3 / Media
# =============================================================================

variable "media_bucket_name" {
  description = "Globally unique name for the media S3 bucket."
  type        = string
  default     = "pasarconnect-media"
}

# =============================================================================
# IRSA
# =============================================================================

variable "media_service_namespace" {
  description = "Kubernetes namespace the media service runs in."
  type        = string
  default     = "pasarconnect"
}

variable "media_service_account_name" {
  description = "Kubernetes ServiceAccount name for the media service."
  type        = string
  default     = "media-service"
}
