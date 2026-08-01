variable "name_prefix" { type = string }
variable "environment" { type = string }

variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }
variable "alb_security_group_id" { type = string }
variable "app_security_group_id" { type = string }

variable "kms_key_arn" {
  description = "Shared with the data module, so logs and exports use the same key as the database."
  type        = string
}

variable "secret_arns" {
  description = "CAREOS_ variable name to Secrets Manager ARN, injected into every task."
  type        = map(string)
}

variable "all_secret_arns" {
  description = "Every secret ARN the execution role may read."
  type        = list(string)
}

variable "certificate_arn" {
  description = <<-EOT
    ACM certificate for the API hostname.

    Not created here. A certificate needs DNS validation against a zone this module does not
    own, and a half-created certificate blocks the whole apply until someone adds a record by
    hand. Issue it once, pass the ARN.
  EOT
  type        = string
}

variable "image_tag" {
  description = <<-EOT
    Image tag to deploy. Never `latest`.

    The ECR repository is IMMUTABLE, so a tag identifies exactly one image forever, which is
    what makes a rollback a tag change rather than a rebuild.
  EOT
  type        = string

  validation {
    condition     = var.image_tag != "latest"
    error_message = "Deploy an immutable tag (a commit SHA), not 'latest'."
  }
}

variable "app_port" {
  type    = number
  default = 8000
}

variable "worker_metrics_port" {
  type    = number
  default = 9101
}

variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "api_desired_count" {
  description = "Two minimum in production: one task is a deploy that drops requests."
  type        = number
  default     = 2
}

variable "api_max_count" {
  type    = number
  default = 10
}

variable "worker_cpu" {
  type    = number
  default = 512
}

variable "worker_memory" {
  type    = number
  default = 1024
}

variable "worker_desired_count" {
  description = "Safe to raise — each job takes a per-(job, agency) advisory lock."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  type    = number
  default = 90
}

variable "evv_use_sandbox" {
  description = <<-EOT
    Transmit to vendor sandboxes rather than production aggregators.

    Must be false in production — `validate_settings` refuses to boot otherwise — and must be
    true everywhere else. `03_Technical_Architecture.md` Section 7 forbids pointing staging at
    a production aggregator, because those transmissions are real state filings.
  EOT
  type        = bool
}

variable "screening_adapter" {
  description = "Background-check vendor key. `loopback` is refused in production."
  type        = string

  validation {
    condition     = var.screening_adapter != ""
    error_message = "Name the screening adapter explicitly."
  }
}

variable "screening_use_sandbox" {
  description = "Staging must not order real searches on real people."
  type        = bool
  default     = true
}

variable "cors_allowed_origins" {
  description = <<-EOT
    Origins allowed to call the API from a browser — the caregiver PWA needs this.

    Never a wildcard and never localhost in production; `validate_settings` refuses both.
  EOT
  type        = list(string)
}

variable "tags" {
  type    = map(string)
  default = {}
}
