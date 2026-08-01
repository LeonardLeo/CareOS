# Staging: the same shape as production, smaller and cheaper where that costs nothing real.
#
# What is deliberately identical: three subnet tiers, encryption at rest and in transit, a
# Redis replication group, `CAREOS_RATE_LIMIT_BACKEND=redis`, MFA required. Those are the
# things a cheaper staging would silently stop exercising, and a control that is only on in
# production is a control nobody has tested.
#
# What differs: one NAT gateway, no RDS Multi-AZ, smaller instances, shorter log retention,
# and no deletion protection so this can be torn down and rebuilt.
#
# What must never match: `evv_use_sandbox`. Staging transmits to vendor sandboxes because a
# transmission to a real aggregator is a real state filing about a real Medicaid visit.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state with locking. Create the bucket and table once, out of band, before the
  # first apply — a state file on a laptop is a deployment one person can destroy.
  backend "s3" {
    bucket         = "careos-tfstate"
    key            = "staging/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "careos-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = "CareOS"
      # Everything in this account touches PHI or supports something that does. Tagged so a
      # cost report and a compliance inventory read the same list.
      DataClassification = "phi"
    }
  }
}

locals {
  name_prefix = "careos-staging"
}

module "network" {
  source = "../../modules/network"

  name_prefix        = local.name_prefix
  environment        = "staging"
  region             = var.region
  vpc_cidr           = "10.41.0.0/16"
  single_nat_gateway = true
}

module "data" {
  source = "../../modules/data"

  name_prefix            = local.name_prefix
  environment            = "staging"
  isolated_subnet_ids    = module.network.isolated_subnet_ids
  data_security_group_id = module.network.data_security_group_id

  db_instance_class     = "db.t4g.small"
  db_allocated_storage  = 20
  db_multi_az           = false
  backup_retention_days = 7
  deletion_protection   = false

  redis_node_type  = "cache.t4g.micro"
  redis_node_count = 2

  app_db_password  = var.app_db_password
  auth_db_password = var.auth_db_password
}

module "app" {
  source = "../../modules/app"

  name_prefix = local.name_prefix
  environment = "staging"

  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  private_subnet_ids    = module.network.private_subnet_ids
  alb_security_group_id = module.network.alb_security_group_id
  app_security_group_id = module.network.app_security_group_id

  kms_key_arn     = module.data.kms_key_arn
  secret_arns     = module.data.secret_arns
  all_secret_arns = module.data.all_secret_arns
  certificate_arn = var.certificate_arn
  image_tag       = var.image_tag

  api_cpu              = 512
  api_memory           = 1024
  api_desired_count    = 1
  api_max_count        = 3
  worker_desired_count = 1
  log_retention_days   = 30

  evv_use_sandbox       = true
  screening_adapter     = var.screening_adapter
  screening_use_sandbox = true
  cors_allowed_origins  = var.cors_allowed_origins
}
