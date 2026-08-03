# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Coding Instructions

See [docs/coding-instructions.md](docs/coding-instructions.md) for full coding standards covering Python/FastAPI and React/TypeScript — project structure, code style, testing, and build commands.

## Infrastructure & Configuration (AWS + Python CDK)

All configuration below is production-grade. Infrastructure is defined as code using **AWS CDK (Python)**.

> Note: this repo is a stub — `cdk.json` (the file that points the CDK CLI at `infra/app.py` and is required for any `cdk` command, e.g. `cdk synth`/`deploy`/`destroy`) does not exist yet. Add it before running CDK commands against a real project.

### CDK Project Structure
```
infra/
  app.py              # CDK app entry point
  stacks/
    __init__.py
    network_stack.py   # VPC, subnets, security groups
    backend_stack.py   # ECS/Fargate service for FastAPI
    frontend_stack.py  # S3 + CloudFront for React SPA
    pipeline_stack.py  # CodePipeline CI/CD
  config/
    prod.py            # Production environment config
    staging.py         # Staging environment config
```

### Backend (FastAPI on ECS Fargate)
- Deploy as a Docker container on **ECS Fargate** behind an **ALB**.
- Dockerfile: multi-stage build — `python:3.12-slim` base, install from locked `requirements.lock`, run with `uvicorn --workers 4 --host 0.0.0.0 --port 8000`.
- ALB health check targets `GET /health`.
- Auto-scaling: target 70% CPU utilization, min 2 / max 10 tasks.
- Logs to **CloudWatch Logs** with 30-day retention.
- Secrets (DB credentials, API keys) stored in **AWS Secrets Manager**, injected as environment variables via ECS task definition — never baked into images.
- Use **ECR** for container image registry.

### Frontend (React SPA on S3 + CloudFront)
- `npm run build` output deployed to an **S3 bucket** (private, no public access).
- **CloudFront** distribution with OAC (Origin Access Control) to serve from S3.
- Custom domain via **Route 53** alias record to CloudFront.
- **ACM certificate** in `us-east-1` for HTTPS.
- Cache policy: immutable assets (`/assets/*`) cached 1 year; `index.html` cached 0 seconds (always revalidated).
- Enable CloudFront Functions or Lambda@Edge for SPA routing (return `index.html` for 404s).

### CI/CD Pipeline (CodePipeline + CodeBuild)
- Source: GitHub connection via **CodeStar Connections**.
- Pipeline stages: **Source → Build → Deploy-Staging → Manual Approval → Deploy-Prod**.
- Backend build (CodeBuild):
  1. `pip install -r requirements.txt && pytest` — fail the build on test failure.
  2. Docker build and push to ECR.
  3. Update ECS service (rolling deployment, `minimumHealthyPercent: 100`, `maximumPercent: 200`).
- Frontend build (CodeBuild):
  1. `npm ci && npm run lint && npm run build` — fail on lint or type errors.
  2. `aws s3 sync dist/ s3://<bucket> --delete`
  3. CloudFront cache invalidation on `/*`.
- Separate CodeBuild projects for backend and frontend — they deploy independently.

### Networking
- **VPC** with public and private subnets across 2+ AZs.
- ALB in public subnets, ECS tasks in private subnets.
- **NAT Gateway** for outbound internet from private subnets.
- Security groups: ALB allows inbound 443 only; ECS tasks allow inbound from ALB security group on port 8000 only.

### Monitoring & Observability
- **CloudWatch Alarms**: ALB 5xx rate > 1%, ECS CPU > 80%, unhealthy host count > 0.
- **SNS topic** for alarm notifications (email/PagerDuty).
- Structured JSON logging from FastAPI (use `python-json-logger`).
- **X-Ray** tracing on ALB and ECS for request tracing.

### Environment Configuration
- All environment-specific values (domain names, instance counts, feature flags) defined in `infra/config/` Python files — not hardcoded in stacks.
- CDK stacks accept an `env_config` parameter to swap between staging and production.
- Tag all resources with `Environment`, `Service`, and `Owner` tags.
- Enable **CDK Nag** (`cdk-nag`) in the pipeline to enforce AWS best practices and catch security issues before deployment.
