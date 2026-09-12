# DevOps-Based Disaster Recovery System

An automated, cross-region disaster recovery and high-availability infrastructure framework designed to ensure business continuity during regional cloud outages.

Comprehensive architectural specifications, recovery objectives, component designs, and Mermaid sequence/topology diagrams are documented in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Repository Layout

```text
.
├── .gitignore                      # Git ignore rules for Python, Terraform, IDEs, and artifacts
├── ARCHITECTURE.md                 # DR specification (RTO/RPO, components, Mermaid diagrams)
├── README.md                       # Project overview, layout tree, and quickstart documentation
├── infrastructure/
│   └── terraform/
│       └── main.tf                 # Multi-region IaC (VPCs, RDS cross-region replica, S3 CRR, Route 53)
├── monitoring/
│   └── prometheus.yml              # Telemetry configuration, replication lag alerts & synthetic probes
├── scripts/
│   ├── failover.sh                 # Automated DR failover orchestration script (dry-run supported)
│   └── health_check.sh             # HTTP endpoint health probe and readiness validation script
├── src/
│   └── app.py                      # Core health service exposing /, /healthz, /readyz, and /metrics
└── tests/
    └── test_app.py                 # Unit and integration test suite for the health service
```

---

## Key Metrics & Objectives

* **Recovery Time Objective (RTO):** `< 15 minutes` (Tier 1 services recover in `≤ 5 minutes`).
* **Recovery Point Objective (RPO):** `< 5 minutes` (Continuous asynchronous database replication and 60s WAL shipping).
* **High Availability SLA:** `99.99%` uptime across multi-AZ and multi-region warm standby topology.

---

## Quickstart Guide

### 1. Running the Health Status Service
The service uses Python's standard library with zero external dependencies:

```bash
# Start on default port 8080
python src/app.py

# Custom region or standby role
APP_REGION="dr-us-west-2" APP_ROLE="standby" python src/app.py
```

Endpoints exposed:
* `GET /` or `GET /healthz` - Service health status and metadata (JSON)
* `GET /livez` - Basic process liveness probe
* `GET /readyz` - Application and dependency readiness probe
* `GET /metrics` - Prometheus metrics format

### 2. Running the Test Suite
Execute the automated test suite using Python's built-in `unittest` framework:

```bash
python -m unittest discover tests
```

### 3. Probing Service Health
Run the health check probe script:

```bash
# Verify local or remote service
./scripts/health_check.sh http://localhost:8080/healthz
```

### 4. Executing Automated Failover
Simulate or execute the disaster recovery failover workflow:

```bash
# Dry-run mode (safe preview)
./scripts/failover.sh --dry-run

# Live execution with specific endpoints
./scripts/failover.sh --primary-endpoint http://primary:8080/healthz --secondary-endpoint http://secondary:8080/healthz
```

### 5. Infrastructure Deployment (Terraform)
Initialize and validate the multi-region infrastructure definition:

```bash
cd infrastructure/terraform
terraform init
terraform validate
terraform plan
```
