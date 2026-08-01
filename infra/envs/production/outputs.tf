output "alb_dns_name" { value = module.app.alb_dns_name }
output "ecr_repository_url" { value = module.app.ecr_repository_url }
output "cluster_name" { value = module.app.cluster_name }
output "migrate_task_family" { value = module.app.migrate_task_family }
