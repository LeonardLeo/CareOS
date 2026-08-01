output "db_address" {
  value = aws_db_instance.this.address
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "kms_key_arn" {
  description = "Also used by the app module to encrypt log groups and the export bucket."
  value       = aws_kms_key.data.arn
}

output "secret_arns" {
  description = "Every secret the task definitions inject, by CAREOS_ environment variable name."
  value = {
    CAREOS_DATABASE_URL            = aws_secretsmanager_secret.database_url.arn
    CAREOS_PRIVILEGED_DATABASE_URL = aws_secretsmanager_secret.privileged_database_url.arn
    CAREOS_MIGRATION_DATABASE_URL  = aws_secretsmanager_secret.migration_database_url.arn
    CAREOS_REDIS_URL               = aws_secretsmanager_secret.redis_url.arn
    CAREOS_JWT_SECRET              = aws_secretsmanager_secret.application["jwt-secret"].arn
    CAREOS_FIELD_ENCRYPTION_KEY    = aws_secretsmanager_secret.application["field-encryption-key"].arn
    CAREOS_METRICS_TOKEN           = aws_secretsmanager_secret.application["metrics-token"].arn
  }
}

output "all_secret_arns" {
  description = "For the IAM policy that lets a task read them."
  value = concat(
    [
      aws_secretsmanager_secret.database_url.arn,
      aws_secretsmanager_secret.privileged_database_url.arn,
      aws_secretsmanager_secret.migration_database_url.arn,
      aws_secretsmanager_secret.redis_url.arn,
    ],
    [for s in aws_secretsmanager_secret.application : s.arn],
  )
}
