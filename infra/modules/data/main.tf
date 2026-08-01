# Postgres and Redis, in the isolated subnets.
#
# Three things here are not defaults and are not negotiable:
#
# **Encryption at rest with a customer-managed key.** `08_Security_Architecture.md` Section 3
# requires it, and a customer-managed key rather than the AWS-managed default is what makes
# key rotation and revocation the agency's story to tell rather than Amazon's.
#
# **Encryption in transit, enforced by the server.** `rds.force_ssl` refuses a plaintext
# connection at the database rather than trusting every client to ask for TLS. The
# application's connection strings say `sslmode=require`; this is what makes that true even
# when one of them does not.
#
# **Redis as a replication group, not a single node.** `careos.core.ratelimit` puts the shared
# token buckets there, and `validate_settings` refuses to boot production on in-process
# buckets. A single-node Redis therefore turns a cache failure into a total outage.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

locals {
  tags = merge(var.tags, {
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "data"
  })
}

# --- Key ---------------------------------------------------------------------------------

resource "aws_kms_key" "data" {
  description             = "${var.name_prefix} data at rest (RDS, ElastiCache, backups)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  tags = merge(local.tags, { Name = "${var.name_prefix}-data" })
}

resource "aws_kms_alias" "data" {
  name          = "alias/${var.name_prefix}-data"
  target_key_id = aws_kms_key.data.key_id
}

# --- Postgres ----------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.isolated_subnet_ids
  tags       = merge(local.tags, { Name = "${var.name_prefix}-db" })
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name_prefix}-pg16"
  family = "postgres16"

  # Refuse unencrypted connections at the server. A client that forgets `sslmode=require`
  # fails to connect rather than succeeding in plaintext, which is the difference between a
  # configuration mistake and a silent one.
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # Log every statement that takes longer than a second. The `careos_app` role runs under RLS,
  # so a query plan that stopped using an index shows up here as a latency cliff before it
  # shows up as a support ticket.
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  # Row-Level Security is the tenant boundary (`08_Security_Architecture.md` Section 2). The
  # application connects as `careos_app`, which has no BYPASSRLS, and every table carries
  # FORCE ROW LEVEL SECURITY — but a superuser connection would still bypass it, so nothing
  # in the deployment ever uses the master credentials except migrations.
  parameter {
    name  = "log_connections"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = local.tags
}

resource "random_password" "db_master" {
  length  = 40
  special = false # RDS rejects several punctuation characters in a master password.
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.postgres_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  db_name  = "careos"
  username = "careos_root"
  password = random_password.db_master.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.data_security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name
  publicly_accessible    = false

  multi_az = var.db_multi_az

  # PHI. `06_Compliance_and_Regulatory_Requirements.md` Section 2 requires retention well past
  # a week; 35 days is the RDS maximum for automated backups and the floor for anything
  # longer, which is what the snapshot export in `08_Security_Architecture.md` Section 4 is
  # for.
  backup_retention_period  = var.backup_retention_days
  backup_window            = "07:00-08:00" # UTC — outside US business hours in every timezone.
  copy_tags_to_snapshot    = true
  delete_automated_backups = false

  maintenance_window          = "sun:08:00-sun:09:00"
  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false

  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.data.arn
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  # A production database that can be destroyed by a `terraform apply` is one that eventually
  # is. Staging sets this false so it can be torn down and rebuilt.
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${var.name_prefix}-final" : null

  # The master password is rotated out of band and read from Secrets Manager thereafter; the
  # Terraform state's copy is the initial value only.
  lifecycle {
    ignore_changes = [password]
  }

  tags = merge(local.tags, { Name = "${var.name_prefix}-postgres" })
}

resource "aws_iam_role" "rds_monitoring" {
  name               = "${var.name_prefix}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.rds_monitoring_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "rds_monitoring_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# --- Redis -------------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis"
  subnet_ids = var.isolated_subnet_ids
  tags       = local.tags
}

resource "random_password" "redis_auth" {
  length  = 64
  special = false # ElastiCache AUTH tokens are restricted to a narrow character set.
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name_prefix}-redis"
  description          = "${var.name_prefix} rate limiter and cache"

  engine         = "redis"
  engine_version = var.redis_version
  node_type      = var.redis_node_type
  port           = 6379

  # Two nodes minimum, with automatic failover. The rate limiter is a hard dependency in
  # production — `validate_settings` refuses to boot on in-process buckets — so a single node
  # would make a cache failure an outage.
  num_cache_clusters         = var.redis_node_count
  automatic_failover_enabled = var.redis_node_count > 1
  multi_az_enabled           = var.redis_node_count > 1

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.data_security_group_id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  snapshot_retention_limit = var.environment == "production" ? 7 : 1
  snapshot_window          = "05:00-06:00"
  maintenance_window       = "sun:06:00-sun:07:00"

  apply_immediately = var.environment != "production"

  tags = merge(local.tags, { Name = "${var.name_prefix}-redis" })
}

# --- Secrets -----------------------------------------------------------------------------
#
# `08_Security_Architecture.md` Section 5: no secret is ever committed, and deployed
# environments read them from a secrets manager at deploy time. These are the ones Terraform
# generates; the rest — JWT signing key, field-encryption key, vendor credentials — are
# created empty here and populated out of band, so that a `terraform apply` never has them.

resource "aws_secretsmanager_secret" "database_url" {
  name       = "${var.name_prefix}/database-url"
  kms_key_id = aws_kms_key.data.arn
  tags       = local.tags
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  # The *application* role, not the master. `careos_app` has no BYPASSRLS, which is what makes
  # Row-Level Security the tenant boundary rather than a suggestion. The role itself is
  # created by `services/api/scripts/bootstrap_db.sql`, run once against a fresh instance.
  secret_string = join("", [
    "postgresql+asyncpg://careos_app:",
    var.app_db_password,
    "@",
    aws_db_instance.this.address,
    ":5432/careos?ssl=require",
  ])
}

resource "aws_secretsmanager_secret" "privileged_database_url" {
  name       = "${var.name_prefix}/privileged-database-url"
  kms_key_id = aws_kms_key.data.arn
  tags       = local.tags
}

resource "aws_secretsmanager_secret_version" "privileged_database_url" {
  secret_id = aws_secretsmanager_secret.privileged_database_url.id
  # The narrow BYPASSRLS role: login lookups and agency provisioning only.
  secret_string = join("", [
    "postgresql+asyncpg://careos_auth:",
    var.auth_db_password,
    "@",
    aws_db_instance.this.address,
    ":5432/careos?ssl=require",
  ])
}

resource "aws_secretsmanager_secret" "migration_database_url" {
  name       = "${var.name_prefix}/migration-database-url"
  kms_key_id = aws_kms_key.data.arn
  tags       = local.tags
}

resource "aws_secretsmanager_secret_version" "migration_database_url" {
  secret_id = aws_secretsmanager_secret.migration_database_url.id
  secret_string = join("", [
    "postgresql+asyncpg://careos_root:",
    random_password.db_master.result,
    "@",
    aws_db_instance.this.address,
    ":5432/careos?ssl=require",
  ])
}

resource "aws_secretsmanager_secret" "redis_url" {
  name       = "${var.name_prefix}/redis-url"
  kms_key_id = aws_kms_key.data.arn
  tags       = local.tags
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id = aws_secretsmanager_secret.redis_url.id
  # `rediss://` — TLS. `transit_encryption_enabled` above makes a plaintext `redis://` fail
  # to connect rather than silently downgrade.
  secret_string = join("", [
    "rediss://:",
    random_password.redis_auth.result,
    "@",
    aws_elasticache_replication_group.this.primary_endpoint_address,
    ":6379/0",
  ])
}

# Created empty and populated out of band. A `terraform apply` that could read the JWT signing
# key would put it in the state file, and the state file is not where it belongs.
resource "aws_secretsmanager_secret" "application" {
  for_each = toset([
    "jwt-secret",
    "field-encryption-key",
    "metrics-token",
    "screening-vendor-credentials",
    "evv-vendor-credentials",
  ])

  name        = "${var.name_prefix}/${each.value}"
  kms_key_id  = aws_kms_key.data.arn
  description = "Populated out of band. Terraform creates the container, never the value."
  tags        = local.tags
}
