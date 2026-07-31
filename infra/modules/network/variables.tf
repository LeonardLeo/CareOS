variable "name_prefix" {
  description = "Prefix for every resource name, e.g. careos-staging."
  type        = string
}

variable "environment" {
  description = "staging or production. Tagged onto everything, and read by cost reporting."
  type        = string
}

variable "region" {
  description = "AWS region. Used to build VPC endpoint service names."
  type        = string
}

variable "vpc_cidr" {
  description = "IPv4 range for the VPC. /16 leaves room for the three /24 tiers per AZ."
  type        = string
  default     = "10.40.0.0/16"
}

variable "app_port" {
  description = "Port the API container listens on."
  type        = number
  default     = 8000
}

variable "worker_metrics_port" {
  description = "Port the worker serves its own /metrics on."
  type        = number
  default     = 9101
}

variable "single_nat_gateway" {
  description = <<-EOT
    One NAT gateway shared across AZs instead of one per AZ.

    True is a staging economy. False in production: losing outbound traffic loses EVV
    transmission, and EVV transmission has a regulatory deadline attached to it.
  EOT
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
