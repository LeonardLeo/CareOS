# Production.
#
# Every difference from staging is either capacity or a thing that must not be tested here.
#
# `evv_use_sandbox = false` is the one that matters and the one that cannot be got wrong in
# either direction. False means transmissions are real state filings about real Medicaid
# visits. `careos.config.validate_settings` refuses to boot production with it true, so the
# guard exists in two places on purpose.
#
# Before the first apply: the state bucket and lock table exist; the `careos_app` and
# `careos_auth` roles have been created against the fresh instance by
# `services/api/scripts/bootstrap_db.sql`; the ACM certificate is issued and validated; and a
# signed BAA is in place with AWS. That last one is not optional and not something Terraform
# can assert — PHI reaching an account with no BAA is the breach, not a step towards one.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "careos-tfstate"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "careos-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project            = "CareOS"
      DataClassification = "phi"
    }
  }
}

locals {
  name_prefix = "careos-production"
}

module "network" {
  source = "../../modules/network"

  name_prefix = local.name_prefix
  environment = "production"
  region      = var.region
  vpc_cidr    = "10.42.0.0/16"

  # One NAT per AZ. Losing outbound loses EVV transmission, and EVV transmission has a
  # regulatory deadline attached to it rather than a user waiting.
  single_nat_gateway = false
}

module "data" {
  source = "../../modules/data"

  name_prefix            = local.name_prefix
  environment            = "production"
  isolated_subnet_ids    = module.network.isolated_subnet_ids
  data_security_group_id = module.network.data_security_group_id

  db_instance_class     = var.db_instance_class
  db_allocated_storage  = 100
  db_multi_az           = true
  backup_retention_days = 35
  deletion_protection   = true

  redis_node_type  = "cache.t4g.small"
  redis_node_count = 2

  app_db_password  = var.app_db_password
  auth_db_password = var.auth_db_password
}

module "app" {
  source = "../../modules/app"

  name_prefix = local.name_prefix
  environment = "production"

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

  api_desired_count    = 2
  api_max_count        = 10
  worker_desired_count = 2

  # Six years, the HIPAA documentation-retention floor in
  # `06_Compliance_and_Regulatory_Requirements.md` Section 2. Application logs are not the
  # audit trail — that lives in `audit_log`, in Postgres — but they are what an incident
  # reconstruction reads, and an incident can surface long after the fact.
  log_retention_days = 2192

  evv_use_sandbox       = false
  screening_adapter     = var.screening_adapter
  screening_use_sandbox = false
  cors_allowed_origins  = var.cors_allowed_origins
}
