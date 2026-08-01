variable "name_prefix" { type = string }
variable "environment" { type = string }

variable "isolated_subnet_ids" {
  description = "Subnets with no route to a NAT gateway."
  type        = list(string)
}

variable "data_security_group_id" {
  description = "Reachable from the application tier only."
  type        = string
}

variable "postgres_version" {
  type    = string
  default = "16.4"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_allocated_storage" {
  type    = number
  default = 50
}

variable "db_max_allocated_storage" {
  description = "Ceiling for storage autoscaling. Zero disables it."
  type        = number
  default     = 500
}

variable "db_multi_az" {
  description = <<-EOT
    Standby in a second AZ with automatic failover.

    Required in production for the 99.9% NFR. Roughly doubles the instance cost, which is why
    staging runs without it.
  EOT
  type        = bool
  default     = true
}

variable "backup_retention_days" {
  description = "35 is the RDS maximum for automated backups."
  type        = number
  default     = 35
}

variable "deletion_protection" {
  description = "Also controls whether a final snapshot is taken on destroy."
  type        = bool
  default     = true
}

variable "redis_version" {
  type    = string
  default = "7.1"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "redis_node_count" {
  description = "Two or more enables automatic failover and Multi-AZ."
  type        = number
  default     = 2

  validation {
    condition     = var.redis_node_count >= 1
    error_message = "At least one cache node is required."
  }
}

variable "app_db_password" {
  description = <<-EOT
    Password for the unprivileged `careos_app` role.

    Supplied rather than generated: the role is created by `bootstrap_db.sql` against a fresh
    instance, which Terraform does not run, so Terraform cannot know a password it did not set.
    Pass it from the environment's own secret store, never from a committed tfvars file.
  EOT
  type        = string
  sensitive   = true
}

variable "auth_db_password" {
  description = "Password for the narrow BYPASSRLS `careos_auth` role. Same reasoning."
  type        = string
  sensitive   = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
