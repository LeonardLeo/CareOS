# ECS Fargate: the API behind an ALB, the worker beside it, and migrations as a task nothing
# runs automatically.
#
# **Migrations are their own task definition and no service runs them.** The local compose
# file has the API container run `alembic upgrade head` on start, which is fine for one
# container and wrong for two: a rolling deploy starts several API tasks at once and they
# would race on the same database. Here the deploy pipeline runs the migration task to
# completion first, then updates the services. `13_Phase_1_Launch_Plan.md` Phase 1 calls this
# out as the thing to get right, and it is the difference between a deploy and an outage.
#
# **The worker is a separate service, scaled on replica count.** Every job takes a per-(job,
# agency) advisory lock, so replicas divide the tenants between them and adding one is a
# capacity decision rather than a correctness one.

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
  tags = merge(var.tags, {
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "app"
  })

  # Non-secret configuration, identical for every task. Secrets come from Secrets Manager and
  # never appear here — a task definition is readable by anyone with `ecs:DescribeTaskDefinition`.
  #
  # Three of these are boot gates rather than preferences. `careos.config.validate_settings`
  # refuses to start production without MFA required, a Redis-backed rate limiter, and a
  # metrics token, and refuses the loopback screening adapter. Setting them here is what makes
  # the deployment bootable at all, which is deliberate: the failure is at deploy time and
  # loud, not months later and silent.
  common_environment = [
    { name = "CAREOS_ENVIRONMENT", value = var.environment },
    { name = "CAREOS_RATE_LIMIT_BACKEND", value = "redis" },
    { name = "CAREOS_MFA_REQUIRED", value = "true" },
    { name = "CAREOS_EVV_USE_SANDBOX", value = tostring(var.evv_use_sandbox) },
    { name = "CAREOS_SCREENING_ADAPTER", value = var.screening_adapter },
    { name = "CAREOS_SCREENING_USE_SANDBOX", value = tostring(var.screening_use_sandbox) },
    { name = "CAREOS_CORS_ALLOWED_ORIGINS", value = jsonencode(var.cors_allowed_origins) },
  ]

  secret_refs = [
    for name, arn in var.secret_arns : { name = name, valueFrom = arn }
  ]
}

data "aws_region" "current" {}

# --- Image registry ----------------------------------------------------------------------

resource "aws_ecr_repository" "api" {
  name                 = "${var.name_prefix}/api"
  image_tag_mutability = "IMMUTABLE" # A tag that can move is a rollback you cannot trust.

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = local.tags
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 30 images; older ones are older than any rollback window."
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

# --- Logs --------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/careos/${var.environment}/api"
  retention_in_days = var.log_retention_days
  # Logs are structured and deliberately free of PHI, but a stack trace is not something
  # anyone audits line by line. Encrypted with the same key as the database.
  kms_key_id = var.kms_key_arn
  tags       = local.tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/careos/${var.environment}/worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/careos/${var.environment}/migrate"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

# --- IAM ---------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# The execution role pulls the image and reads secrets to inject them. It is used by the ECS
# agent, not by the application, which is why secret access lives here rather than on the
# task role — the container process never gets credentials that can read Secrets Manager.
resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.all_secret_arns
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# The task role is what the application itself holds. Deliberately almost empty: the API talks
# to Postgres, Redis, and vendor HTTPS endpoints, and needs no AWS API access to do any of it.
# The one exception is the export bucket, and only for the API.
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task_exports" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.exports.arn}/*"]
  }
}

resource "aws_iam_role_policy" "task_exports" {
  name   = "agency-exports"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_exports.json
}

# --- Export bucket -----------------------------------------------------------------------
#
# The staged export in `13_Phase_1_Launch_Plan.md` 8.1 is not built yet; the bucket the
# `*_s3_key` columns anticipate is created now because provisioning it later means another
# change to a HIPAA-relevant resource under time pressure.

resource "aws_s3_bucket" "exports" {
  bucket = "${var.name_prefix}-agency-exports"
  tags   = merge(local.tags, { Name = "${var.name_prefix}-agency-exports" })
}

resource "aws_s3_bucket_public_access_block" "exports" {
  bucket                  = aws_s3_bucket.exports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "exports" {
  bucket = aws_s3_bucket.exports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id

  rule {
    id     = "expire-exports"
    status = "Enabled"
    filter {}

    # An export is a plaintext PHI extract of everything an agency holds. It exists so a
    # customer can take their data; it is not an archive, and keeping it around is keeping a
    # copy of the whole database in a bucket.
    expiration {
      days = 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

# --- Load balancer -----------------------------------------------------------------------

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.alb_security_group_id]

  # An ALB that can be deleted by an errant apply takes the DNS record with it.
  enable_deletion_protection = var.environment == "production"
  drop_invalid_header_fields = true

  access_logs {
    bucket  = aws_s3_bucket.alb_logs.id
    prefix  = "alb"
    enabled = true
  }

  tags = local.tags
}

resource "aws_s3_bucket" "alb_logs" {
  bucket        = "${var.name_prefix}-alb-logs"
  force_destroy = var.environment != "production"
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket                  = aws_s3_bucket.alb_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ALB access logging uses a regional AWS-owned account and does not support KMS-CMK, so this
# bucket takes SSE-S3. Access logs carry request paths and source addresses, not bodies.
resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_elb_service_account" "main" {}

data "aws_iam_policy_document" "alb_logs" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.alb_logs.arn}/*"]
    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.main.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  policy = data.aws_iam_policy_document.alb_logs.json
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name_prefix}-api"
  port        = var.app_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Long enough for an in-flight clock-out to finish. Short enough that a deploy is not a
  # coffee break.
  deregistration_delay = 30

  tags = local.tags
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  # TLS 1.2 floor. `08_Security_Architecture.md` Section 3 requires TLS 1.2 or better in
  # transit, and the 1.3-only policies would exclude older Android handsets — which is a
  # caregiver's phone, not a nice-to-have.
  ssl_policy      = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# --- Cluster and task definitions ---------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{
      containerPort = var.app_port
      protocol      = "tcp"
    }]
    command     = ["uvicorn", "careos.main:app", "--host", "0.0.0.0", "--port", tostring(var.app_port)]
    environment = local.common_environment
    secrets     = local.secret_refs
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "api"
      }
    }
    # The ALB health-checks the same path. This one exists so a task that is up but not
    # serving is replaced by ECS rather than only being taken out of rotation.
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:${var.app_port}/health', timeout=3).status == 200 else 1)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 20
    }
  }])

  tags = local.tags
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential = true
    command   = ["python", "-m", "careos.workers.runner"]
    portMappings = [{
      containerPort = var.worker_metrics_port
      protocol      = "tcp"
    }]
    environment = concat(local.common_environment, [
      { name = "CAREOS_WORKER_METRICS_PORT", value = tostring(var.worker_metrics_port) },
    ])
    secrets = local.secret_refs
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])

  tags = local.tags
}

# Run to completion by the deploy pipeline, before the services roll. No ECS service points
# at it — that is the whole point. Two API containers racing `alembic upgrade head` is how a
# deploy deadlocks on a lock nobody expected.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name        = "migrate"
    image       = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential   = true
    command     = ["alembic", "upgrade", "head"]
    environment = local.common_environment
    secrets     = local.secret_refs
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.migrate.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])

  tags = local.tags
}

# --- Services ----------------------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "${var.name_prefix}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.app_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.app_port
  }

  # Roll one at a time with the old tasks still serving. `deployment_minimum_healthy_percent`
  # at 100 is what makes a deploy invisible to a caregiver mid-clock-in.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = 30
  enable_execute_command            = var.environment != "production"

  # The pipeline updates the task definition; Terraform should not fight it on the next apply.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.https]
  tags       = local.tags
}

resource "aws_ecs_service" "worker" {
  name            = "${var.name_prefix}-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.app_security_group_id]
    assign_public_ip = false
  }

  # No load balancer and no minimum-healthy constraint. Every job takes a per-(job, agency)
  # advisory lock, so a replacement worker starting before the old one has stopped simply
  # skips the agencies the other holds. SIGTERM stops it between agencies, not mid-delivery.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = local.tags
}

# --- Autoscaling -------------------------------------------------------------------------

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.api_desired_count
  max_capacity       = var.api_max_count
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.name_prefix}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# The worker is deliberately not autoscaled on CPU. Its load is tenant count, not request
# volume, and it spends most of its time waiting on network calls — CPU would read low while
# the queue backed up. Scale it on replica count when the tenant count grows.
