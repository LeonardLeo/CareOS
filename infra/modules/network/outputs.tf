output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Load balancer only. Nothing that holds PHI runs here."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Application containers. Outbound via NAT, no inbound from the internet."
  value       = aws_subnet.private[*].id
}

output "isolated_subnet_ids" {
  description = "Postgres and Redis. No route to a NAT gateway, by design."
  value       = aws_subnet.isolated[*].id
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "app_security_group_id" {
  value = aws_security_group.app.id
}

output "data_security_group_id" {
  value = aws_security_group.data.id
}
