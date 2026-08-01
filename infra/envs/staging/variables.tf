variable "region" {
  type    = string
  default = "us-east-1"
}

variable "certificate_arn" {
  description = "ACM certificate for the staging API hostname."
  type        = string
}

variable "image_tag" {
  description = "Commit SHA of the image to deploy."
  type        = string
}

variable "screening_adapter" {
  description = "Background-check vendor key. Never `loopback` outside local and test."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Origins the caregiver PWA calls from. No wildcard, no localhost."
  type        = list(string)
}

variable "app_db_password" {
  type      = string
  sensitive = true
}

variable "auth_db_password" {
  type      = string
  sensitive = true
}
