# =============================================================================
# Root module — wires all sub-modules together
# =============================================================================

module "vpc" {
  source = "./modules/vpc"

  project            = var.project
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

module "eks" {
  source = "./modules/eks"

  project                 = var.project
  environment             = var.environment
  eks_cluster_version     = var.eks_cluster_version
  private_subnet_ids      = module.vpc.private_subnet_ids
  eks_nodes_sg_id         = module.vpc.eks_nodes_sg_id
  on_demand_instance_type = var.on_demand_instance_type
  spot_instance_types     = var.spot_instance_types
  on_demand_desired       = var.on_demand_desired
  spot_desired            = var.spot_desired
  spot_min                = var.spot_min
  spot_max                = var.spot_max
}

module "rds" {
  source = "./modules/rds"

  project               = var.project
  environment           = var.environment
  private_subnet_ids    = module.vpc.private_subnet_ids
  data_plane_sg_id      = module.vpc.data_plane_sg_id
  rds_instance_class    = var.rds_instance_class
  rds_master_username   = var.rds_master_username
  rds_master_password   = var.rds_master_password
  rds_logical_databases = var.rds_logical_databases
}

module "documentdb" {
  source = "./modules/documentdb"

  project               = var.project
  environment           = var.environment
  private_subnet_ids    = module.vpc.private_subnet_ids
  data_plane_sg_id      = module.vpc.data_plane_sg_id
  docdb_instance_class  = var.docdb_instance_class
  docdb_master_username = var.docdb_master_username
  docdb_master_password = var.docdb_master_password
}

module "amazonmq" {
  source = "./modules/amazonmq"

  project            = var.project
  environment        = var.environment
  private_subnet_ids = module.vpc.private_subnet_ids
  data_plane_sg_id   = module.vpc.data_plane_sg_id
  mq_instance_type   = var.mq_instance_type
  mq_username        = var.mq_username
  mq_password        = var.mq_password
}

module "s3" {
  source = "./modules/s3"

  project           = var.project
  environment       = var.environment
  media_bucket_name = var.media_bucket_name
}

module "irsa" {
  source = "./modules/irsa"

  project                    = var.project
  environment                = var.environment
  cluster_oidc_issuer_url    = module.eks.cluster_oidc_issuer_url
  oidc_provider_arn          = module.eks.oidc_provider_arn
  media_bucket_arn           = module.s3.bucket_arn
  media_service_namespace    = var.media_service_namespace
  media_service_account_name = var.media_service_account_name
}
