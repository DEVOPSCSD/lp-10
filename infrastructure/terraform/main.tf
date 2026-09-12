# ==============================================================================
# Terraform Infrastructure Specification
# DevOps-Based Disaster Recovery System (Active-Passive / Warm Standby)
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ------------------------------------------------------------------------------
# Provider Configurations (Multi-Region)
# ------------------------------------------------------------------------------
provider "aws" {
  alias  = "primary"
  region = var.primary_region

  default_tags {
    tags = local.common_tags
  }
}

provider "aws" {
  alias  = "secondary"
  region = var.secondary_region

  default_tags {
    tags = merge(local.common_tags, {
      Role = "disaster-recovery"
    })
  }
}

# ------------------------------------------------------------------------------
# Input Variables
# ------------------------------------------------------------------------------
variable "project_name" {
  description = "Project name identifier"
  type        = string
  default     = "devops-dr-system"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

variable "primary_region" {
  description = "Primary active cloud region"
  type        = string
  default     = "us-east-1"
}

variable "secondary_region" {
  description = "Secondary warm standby disaster recovery region"
  type        = string
  default     = "us-west-2"
}

variable "domain_name" {
  description = "Base domain name for Route 53 routing"
  type        = string
  default     = "dr.internal.local"
}

variable "db_instance_class" {
  description = "Database compute instance type"
  type        = string
  default     = "db.t4g.medium"
}

# ------------------------------------------------------------------------------
# Local Variables
# ------------------------------------------------------------------------------
locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    RTO_Target  = "<15m"
    RPO_Target  = "<5m"
  }
}

# ------------------------------------------------------------------------------
# Networking - Primary Region
# ------------------------------------------------------------------------------
resource "aws_vpc" "primary_vpc" {
  provider             = aws.primary
  cidr_block           = "10.10.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-primary-vpc"
  }
}

resource "aws_subnet" "primary_public_1" {
  provider          = aws.primary
  vpc_id            = aws_vpc.primary_vpc.id
  cidr_block        = "10.10.1.0/24"
  availability_zone = "${var.primary_region}a"

  tags = {
    Name = "${var.project_name}-primary-public-1"
  }
}

resource "aws_subnet" "primary_public_2" {
  provider          = aws.primary
  vpc_id            = aws_vpc.primary_vpc.id
  cidr_block        = "10.10.2.0/24"
  availability_zone = "${var.primary_region}b"

  tags = {
    Name = "${var.project_name}-primary-public-2"
  }
}

# ------------------------------------------------------------------------------
# Networking - Secondary DR Region
# ------------------------------------------------------------------------------
resource "aws_vpc" "secondary_vpc" {
  provider             = aws.secondary
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-secondary-dr-vpc"
  }
}

resource "aws_subnet" "secondary_public_1" {
  provider          = aws.secondary
  vpc_id            = aws_vpc.secondary_vpc.id
  cidr_block        = "10.20.1.0/24"
  availability_zone = "${var.secondary_region}a"

  tags = {
    Name = "${var.project_name}-secondary-public-1"
  }
}

resource "aws_subnet" "secondary_public_2" {
  provider          = aws.secondary
  vpc_id            = aws_vpc.secondary_vpc.id
  cidr_block        = "10.20.2.0/24"
  availability_zone = "${var.secondary_region}b"

  tags = {
    Name = "${var.project_name}-secondary-public-2"
  }
}

# ------------------------------------------------------------------------------
# Database Tier: Primary Master & Cross-Region Read Replica
# ------------------------------------------------------------------------------
resource "aws_db_subnet_group" "primary_db_subnet_group" {
  provider   = aws.primary
  name       = "${var.project_name}-primary-db-subnet-group"
  subnet_ids = [aws_subnet.primary_public_1.id, aws_subnet.primary_public_2.id]
}

resource "aws_db_subnet_group" "secondary_db_subnet_group" {
  provider   = aws.secondary
  name       = "${var.project_name}-secondary-db-subnet-group"
  subnet_ids = [aws_subnet.secondary_public_1.id, aws_subnet.secondary_public_2.id]
}

resource "aws_db_instance" "primary_db" {
  provider               = aws.primary
  identifier             = "${var.project_name}-primary-db"
  allocated_storage      = 50
  max_allocated_storage  = 200
  storage_type           = "gp3"
  engine                 = "postgres"
  engine_version         = "15.4"
  instance_class         = var.db_instance_class
  db_name                = "appdb"
  username               = "dbadmin"
  password               = "ChangeMeInSecureSecretVault123!" # Pass via Secrets Manager in production
  db_subnet_group_name   = aws_db_subnet_group.primary_db_subnet_group.name
  skip_final_snapshot    = true
  multi_az               = true
  backup_retention_period = 30
  backup_window          = "02:00-03:00"

  tags = {
    Name = "${var.project_name}-primary-db"
    Role = "master"
  }
}

resource "aws_db_instance" "secondary_replica_db" {
  provider               = aws.secondary
  identifier             = "${var.project_name}-secondary-replica-db"
  replicate_source_db    = aws_db_instance.primary_db.arn
  instance_class         = var.db_instance_class
  storage_type           = "gp3"
  db_subnet_group_name   = aws_db_subnet_group.secondary_db_subnet_group.name
  skip_final_snapshot    = true
  backup_retention_period = 7

  tags = {
    Name = "${var.project_name}-secondary-replica-db"
    Role = "cross-region-replica"
  }
}

# ------------------------------------------------------------------------------
# Object Storage Tier: Primary Bucket & Cross-Region Replication (CRR)
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "secondary_bucket" {
  provider = aws.secondary
  bucket   = "${var.project_name}-backup-${var.secondary_region}"
}

resource "aws_s3_bucket_versioning" "secondary_versioning" {
  provider = aws.secondary
  bucket   = aws_s3_bucket.secondary_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket" "primary_bucket" {
  provider = aws.primary
  bucket   = "${var.project_name}-assets-${var.primary_region}"
}

resource "aws_s3_bucket_versioning" "primary_versioning" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

# ------------------------------------------------------------------------------
# DNS & Traffic Failover (Route 53)
# ------------------------------------------------------------------------------
resource "aws_route53_zone" "primary_zone" {
  provider = aws.primary
  name     = var.domain_name
}

resource "aws_route53_health_check" "primary_health_check" {
  provider          = aws.primary
  fqdn              = "primary-alb.${var.domain_name}"
  port              = 8080
  type              = "HTTP"
  resource_path     = "/healthz"
  failure_threshold = 3
  request_interval  = 10

  tags = {
    Name = "${var.project_name}-primary-health-check"
  }
}

resource "aws_route53_record" "primary_failover" {
  provider       = aws.primary
  zone_id        = aws_route53_zone.primary_zone.zone_id
  name           = "service.${var.domain_name}"
  type           = "A"
  ttl            = 30
  set_identifier = "primary-route"

  failover_routing_policy {
    type = "PRIMARY"
  }

  health_check_id = aws_route53_health_check.primary_health_check.id
  records         = ["10.10.1.100"] # Simulated ALB Virtual IP
}

resource "aws_route53_record" "secondary_failover" {
  provider       = aws.primary
  zone_id        = aws_route53_zone.primary_zone.zone_id
  name           = "service.${var.domain_name}"
  type           = "A"
  ttl            = 30
  set_identifier = "secondary-route"

  failover_routing_policy {
    type = "SECONDARY"
  }

  records = ["10.20.1.100"] # Simulated DR ALB Virtual IP
}

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------
output "primary_region" {
  description = "Active primary region"
  value       = var.primary_region
}

output "secondary_region" {
  description = "Warm standby DR region"
  value       = var.secondary_region
}

output "primary_db_endpoint" {
  description = "Primary database write endpoint"
  value       = aws_db_instance.primary_db.endpoint
}

output "secondary_db_endpoint" {
  description = "Secondary database read-replica endpoint"
  value       = aws_db_instance.secondary_replica_db.endpoint
}

output "service_fqdn" {
  description = "Global failover domain endpoint"
  value       = "service.${var.domain_name}"
}

output "rto_target" {
  description = "Target Recovery Time Objective"
  value       = local.common_tags.RTO_Target
}

output "rpo_target" {
  description = "Target Recovery Point Objective"
  value       = local.common_tags.RPO_Target
}
