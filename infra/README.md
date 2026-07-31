# Infrastructure

Terraform for two AWS environments, staging and production, in `us-east-1`.

```
infra/
  modules/network/   VPC, three subnet tiers, security groups, VPC endpoints
  modules/data/      RDS Postgres, ElastiCache Redis, KMS, Secrets Manager
  modules/app/       ECS Fargate (api, worker, migrate), ALB, ECR, S3
  envs/staging/
  envs/production/
```

## Before the first apply

Terraform does not create these, and each one blocks it.

| Thing | Why Terraform does not do it |
|---|---|
| A signed BAA with AWS | PHI in an account with no BAA is the breach, not a step towards one. Not a resource |
| State bucket `careos-tfstate` and lock table `careos-tflock` | The thing that holds the state cannot be created by the thing that reads it |
| An ACM certificate for the API hostname, validated | Validation needs a DNS record in a zone this configuration does not own. A half-created certificate blocks the whole apply |
| `careos_app` and `careos_auth` database roles | Created by `services/api/scripts/bootstrap_db.sql` against the fresh instance. Their passwords are inputs here, not outputs — Terraform cannot know a password it did not set |
| An IAM role for the deploy pipeline | Bootstrapping problem, same as the state bucket |

## Applying

```
cd infra/envs/staging
terraform init
terraform plan  -var-file=staging.tfvars    # never committed
terraform apply -var-file=staging.tfvars
```

`image_tag` is a required variable with no default and rejects `latest`. The ECR repository
is `IMMUTABLE`, so a tag names exactly one image forever — which is what makes a rollback a
tag change rather than a rebuild.

## Deploying

Three steps, in this order. The order is the whole point.

```
# 1. Build and push, tagged with the commit.
docker build -t "$ECR/api:$SHA" services/api
docker push "$ECR/api:$SHA"

# 2. Migrate — once, to completion, before anything serves the new schema.
aws ecs run-task --cluster careos-production \
  --task-definition careos-production-migrate \
  --launch-type FARGATE --network-configuration "$NETWORK" \
  --overrides '{"containerOverrides":[{"name":"migrate","image":"'"$ECR/api:$SHA"'"}]}'
# Wait for it. A migration still running when the services roll is the race this avoids.

# 3. Roll the services.
aws ecs update-service --cluster careos-production --service careos-production-api \
  --task-definition "$(register_task_definition api "$SHA")" --force-new-deployment
aws ecs update-service --cluster careos-production --service careos-production-worker \
  --task-definition "$(register_task_definition worker "$SHA")" --force-new-deployment
```

The local compose file has the API container run `alembic upgrade head` on start. That is
correct for one container and wrong for two — a rolling deploy starts several at once and they
would race. Hence a migration task no service runs.

Both services have `deployment_circuit_breaker` with rollback enabled, so a task that will not
become healthy reverts rather than draining the old ones.

### Rolling back

Re-run step 3 with the previous SHA. Do not re-run step 2: Alembic downgrades are not
exercised, and a schema change that has to be reversed under pressure is a decision for a
human, not a pipeline. Forward-compatible migrations — add a column, deploy, backfill, then
stop writing the old one — are what make a code rollback safe on its own.

## What is deliberately not here

**No OIDC provider.** `08_Security_Architecture.md` Section 1 calls for managed identity, and
`app_user.auth_provider_id` is the seam. Provisioning it before the provider is chosen would
be guessing at a configuration.

**No CloudFront or WAF.** The API is called by two first-party apps and by nothing else; a CDN
in front of it caches nothing. The public site in `apps/site` is a different matter and gets
its own bucket and distribution when it is deployed.

**No autoscaling on the worker.** Its load is tenant count, not request volume, and it spends
most of its time waiting on network calls — CPU would read low while the queue backed up.
Scale it on replica count.

## Verifying it without an AWS account

`terraform validate` needs provider schemas from `registry.terraform.io`. Where that is
unreachable:

```
terraform fmt -recursive -check infra      # syntax and formatting
python3 scripts/check_terraform_wiring.py  # module inputs and outputs agree
```

The wiring check covers what actually breaks when someone edits this: a variable renamed in a
module and not at its call sites, a required variable dropped, an output referenced after it
was deleted. CI runs both, plus a real `terraform validate` per environment.

**Nothing here has been applied to an AWS account.** It has been syntax-checked and
wiring-checked, and CI validates it against real provider schemas. The first `terraform plan`
against a live account will surface things none of that can — a quota, a name collision, an
argument valid in the schema and rejected by the service. Budget a day for it.
