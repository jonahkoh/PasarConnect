terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.28"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # ---------------------------------------------------------------------------
  # Remote state — store in S3 + DynamoDB for locking.
  # Create the bucket and table manually once, then uncomment this block.
  # ---------------------------------------------------------------------------
  # backend "s3" {
  #   bucket         = "pasarconnect-tfstate"
  #   key            = "infra/terraform.tfstate"
  #   region         = "ap-southeast-1"
  #   dynamodb_table = "pasarconnect-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "PasarConnect"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
