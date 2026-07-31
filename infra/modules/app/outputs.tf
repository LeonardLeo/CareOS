output "alb_dns_name" {
  description = "Point the API hostname's ALIAS record here."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "api_service_name" {
  value = aws_ecs_service.api.name
}

output "worker_service_name" {
  value = aws_ecs_service.worker.name
}

output "migrate_task_family" {
  description = "Run to completion before rolling the services. Nothing runs it automatically."
  value       = aws_ecs_task_definition.migrate.family
}

output "exports_bucket" {
  value = aws_s3_bucket.exports.id
}
