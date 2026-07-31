# VPC, subnets, and the security groups that decide what can reach what.
#
# Three subnet tiers rather than two. Public holds only the load balancer; private holds the
# containers; isolated holds the database and cache and has no route to a NAT gateway at all.
# That last tier is the point: a compromised container can be made to talk to the database
# because it is supposed to, but it cannot be made to exfiltrate to the internet from the
# database's own subnet, because there is no path.
#
# `08_Security_Architecture.md` Section 2 requires network isolation between tiers. This is
# where that stops being a diagram.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  # Two AZs, not one. RDS Multi-AZ and an ElastiCache replication group both need a subnet
  # group spanning more than one, and a single-AZ deployment cannot meet the 99.9% NFR in
  # `02_Product_Requirements_Document.md` Section 4 no matter how the application behaves.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  tags = merge(var.tags, {
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "network"
  })
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.tags, { Name = "${var.name_prefix}-vpc" })
}

# --- Subnets -----------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = length(local.azs)

  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = merge(local.tags, {
    Name = "${var.name_prefix}-public-${local.azs[count.index]}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = merge(local.tags, {
    Name = "${var.name_prefix}-private-${local.azs[count.index]}"
    Tier = "private"
  })
}

resource "aws_subnet" "isolated" {
  count = length(local.azs)

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 20)
  availability_zone = local.azs[count.index]

  tags = merge(local.tags, {
    Name = "${var.name_prefix}-isolated-${local.azs[count.index]}"
    Tier = "isolated"
  })
}

# --- Routing -----------------------------------------------------------------------------

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name_prefix}-public" })
}

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# One NAT gateway per AZ in production, one shared in staging. A shared NAT is a single point
# of failure for outbound traffic and is the right trade for a staging bill; production pays
# for the second one because losing outbound means losing EVV transmission, which is a
# compliance deadline rather than an inconvenience.
resource "aws_eip" "nat" {
  count  = var.single_nat_gateway ? 1 : length(local.azs)
  domain = "vpc"
  tags   = merge(local.tags, { Name = "${var.name_prefix}-nat-${count.index}" })
}

resource "aws_nat_gateway" "this" {
  count = var.single_nat_gateway ? 1 : length(local.azs)

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_internet_gateway.this]

  tags = merge(local.tags, { Name = "${var.name_prefix}-nat-${count.index}" })
}

resource "aws_route_table" "private" {
  count  = length(local.azs)
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name_prefix}-private-${count.index}" })
}

resource "aws_route" "private_default" {
  count = length(local.azs)

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[var.single_nat_gateway ? 0 : count.index].id
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# The isolated tier gets a route table with no default route. Deliberately empty: this is the
# control, and adding a NAT route here later would silently undo it.
resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name_prefix}-isolated" })
}

resource "aws_route_table_association" "isolated" {
  count          = length(aws_subnet.isolated)
  subnet_id      = aws_subnet.isolated[count.index].id
  route_table_id = aws_route_table.isolated.id
}

# --- Security groups ---------------------------------------------------------------------
#
# Referenced by group rather than by CIDR wherever one AWS resource talks to another. A CIDR
# rule keeps working after the thing it was written for is replaced by something else in the
# same range; a group reference does not.

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Public load balancer"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from the internet"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# Port 80 is open only to be redirected. Nothing is served on it — see the ALB listener.
resource "aws_vpc_security_group_ingress_rule" "alb_http_redirect" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP, redirected to HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To the application containers"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = var.app_port
  to_port                      = var.app_port
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "app" {
  name        = "${var.name_prefix}-app"
  description = "API and worker containers"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-app" })
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  description                  = "From the load balancer only"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.app_port
  to_port                      = var.app_port
  ip_protocol                  = "tcp"
}

# The worker's metrics port, reachable only from inside the VPC. `careos.workers.runner`
# serves it on its own listener with the same bearer token as the API's, so a scrape still
# has to authenticate; this keeps it off the internet as well.
resource "aws_vpc_security_group_ingress_rule" "worker_metrics" {
  security_group_id = aws_security_group.app.id
  description       = "Worker metrics, VPC-internal"
  cidr_ipv4         = var.vpc_cidr
  from_port         = var.worker_metrics_port
  to_port           = var.worker_metrics_port
  ip_protocol       = "tcp"
}

# Outbound is unrestricted because the application legitimately calls out: EVV aggregators,
# the background-check vendor, customer webhook endpoints. Narrowing this to an allowlist of
# vendor IPs is worth doing once those endpoints are known and stable, and pretending to do
# it now with a guessed list would be worse than not doing it.
resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "Vendor APIs, customer webhook receivers, AWS service endpoints"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "data" {
  name        = "${var.name_prefix}-data"
  description = "Postgres and Redis"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-data" })
}

resource "aws_vpc_security_group_ingress_rule" "postgres_from_app" {
  security_group_id            = aws_security_group.data.id
  description                  = "Postgres from the application tier only"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_app" {
  security_group_id            = aws_security_group.data.id
  description                  = "Redis from the application tier only"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

# No egress rule on the data group at all. Its subnets have no default route either, so this
# is belt and braces — and both are cheap next to a database that can reach the internet.

# --- VPC endpoints -----------------------------------------------------------------------
#
# So the containers can pull images and read secrets without that traffic leaving the VPC.
# Also cheaper than NAT for the volume ECR pulls generate.

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(aws_route_table.private[*].id, [aws_route_table.isolated.id])
  tags              = merge(local.tags, { Name = "${var.name_prefix}-s3" })
}

resource "aws_security_group" "endpoints" {
  name        = "${var.name_prefix}-endpoints"
  description = "Interface VPC endpoints"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.tags, { Name = "${var.name_prefix}-endpoints" })
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_from_app" {
  security_group_id            = aws_security_group.endpoints.id
  description                  = "HTTPS from the application tier"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset([
    "ecr.api",
    "ecr.dkr",
    "secretsmanager",
    "logs",
    "kms",
  ])

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = merge(local.tags, { Name = "${var.name_prefix}-${replace(each.value, ".", "-")}" })
}
