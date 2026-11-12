# Meeting Assistant — GCP Cloud Run deployment helpers
#
# Prerequisites: gcloud CLI, Docker, billing enabled on PROJECT_ID.
# Copy deploy/.env.prod.example → deploy/.env.prod and fill in values before deploy.

SHELL := /bin/bash
.DEFAULT_GOAL := help

-include deploy/.env.prod

export

IMAGE_NAME ?= meeting-assistant
IMAGE_TAG  ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo latest)
ARTIFACT_REPO ?= meeting-assistant
SERVICE_API ?= meeting-assistant-api
SERVICE_WORKER ?= meeting-assistant-worker
CLOUDSQL_INSTANCE_CONNECTION ?= $(PROJECT_ID):$(REGION):$(CLOUDSQL_INSTANCE)

IMAGE_URI := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(ARTIFACT_REPO)/$(IMAGE_NAME):$(IMAGE_TAG)

# Cloud Run requires linux/amd64. On Apple Silicon, local `docker build` defaults to arm64.
DOCKER_PLATFORM ?= linux/amd64

.PHONY: help
help:
	@echo "Targets:"
	@echo "  make gcp-auth              Authenticate Docker to Artifact Registry"
	@echo "  make gcp-bootstrap         Enable APIs + create Artifact Registry repo"
	@echo "  make cloudsql-create       Create minimal Postgres (Enterprise + db-f1-micro)"
	@echo "  make cloudsql-init         Create DB + user (after cloudsql-create)"
	@echo "  make docker-build          Build container locally"
	@echo "  make docker-push           Build and push to Artifact Registry"
	@echo "  make migrate               Run Alembic migrations (Cloud SQL Auth Proxy must be running)"
	@echo "  make deploy-api            Deploy / update API Cloud Run service"
	@echo "  make deploy-worker         Deploy / update worker Cloud Run service (ARQ or Pub/Sub push)"
	@echo "  make deploy                deploy-api + deploy-worker"
	@echo "  make smoke                 curl /health and /ready on deployed API"
	@echo "  make deploy-bootstrap      Single-service deploy (inprocess queue, for first audio test)"
	@echo ""
	@echo "Pub/Sub batch queue (Phase 14 — set JOB_QUEUE_PROVIDER=pubsub in deploy/.env.prod):"
	@echo "  make pubsub-topic-create       Create Pub/Sub topic for batch jobs"
	@echo "  make pubsub-push-sa-create     Create push-invoker service account"
	@echo "  make pubsub-iam                Grant publisher (API SA) + invoker (push SA on worker)"
	@echo "  make pubsub-subscription-create  Push subscription → worker $(PUBSUB_PUSH_PATH)"
	@echo "  make pubsub-setup              topic + SA + IAM + subscription (worker must exist for sub)"
	@echo ""
	@echo "Local Docker Compose (Postgres + Redis + API + worker):"
	@echo "  make compose-config        Validate docker-compose.yml"
	@echo "  make compose-up            Build and start stack (requires .env.compose)"
	@echo "  make compose-down          Stop stack"
	@echo "  make compose-smoke         curl /health and /ready on local API"
	@echo ""
	@echo "Required in deploy/.env.prod: PROJECT_ID, REGION, CLOUDSQL_INSTANCE, secrets (see deploy/.env.prod.example)"

.PHONY: gcp-auth
gcp-auth:
	gcloud auth configure-docker $(REGION)-docker.pkg.dev --quiet

.PHONY: gcp-bootstrap
gcp-bootstrap:
	gcloud config set project $(PROJECT_ID)
	gcloud services enable \
		run.googleapis.com \
		artifactregistry.googleapis.com \
		secretmanager.googleapis.com \
		sqladmin.googleapis.com \
		redis.googleapis.com \
		storage.googleapis.com \
		cloudbuild.googleapis.com \
		compute.googleapis.com \
		vpcaccess.googleapis.com \
		pubsub.googleapis.com
	gcloud artifacts repositories describe $(ARTIFACT_REPO) \
		--location=$(REGION) >/dev/null 2>&1 \
	|| gcloud artifacts repositories create $(ARTIFACT_REPO) \
		--repository-format=docker \
		--location=$(REGION) \
		--description="Meeting Assistant images"

# Cheapest v1 Postgres: Enterprise edition (required for db-f1-micro / db-g1-small).
# pgvector is enabled by Alembic migration 0002 on first app startup.
# Override tier: make cloudsql-create CLOUDSQL_TIER=db-g1-small
CLOUDSQL_TIER ?= db-f1-micro

.PHONY: cloudsql-create
cloudsql-create:
	gcloud config set project $(PROJECT_ID)
	gcloud services enable sqladmin.googleapis.com --quiet
	gcloud sql instances create $(CLOUDSQL_INSTANCE) \
		--project=$(PROJECT_ID) \
		--database-version=POSTGRES_16 \
		--edition=enterprise \
		--tier=$(CLOUDSQL_TIER) \
		--region=$(REGION) \
		--storage-size=10GB \
		--storage-auto-increase \
		--availability-type=zonal \
		--no-deletion-protection

.PHONY: cloudsql-init
cloudsql-init:
	gcloud sql databases create $(DB_NAME) \
		--instance=$(CLOUDSQL_INSTANCE) \
		--project=$(PROJECT_ID)
	gcloud sql users create $(DB_USER) \
		--instance=$(CLOUDSQL_INSTANCE) \
		--project=$(PROJECT_ID) \
		--password='$(DB_PASSWORD)'

.PHONY: docker-build
docker-build:
	docker build --platform $(DOCKER_PLATFORM) -t $(IMAGE_NAME):$(IMAGE_TAG) .

.PHONY: docker-push
docker-push: gcp-auth
	docker build --platform $(DOCKER_PLATFORM) -t $(IMAGE_URI) .
	docker push $(IMAGE_URI)

# Run locally while Cloud SQL Auth Proxy listens on 127.0.0.1:5432:
#   cloud-sql-proxy $(CLOUDSQL_INSTANCE_CONNECTION)
.PHONY: migrate
migrate:
	uv run alembic upgrade head

AUTH_ENABLED ?= false

OTEL_ENABLED ?= false
OTEL_EXPORTER_ENDPOINT ?=
OTEL_SERVICE_NAME ?= meeting-assistant
OTEL_WORKER_SERVICE_NAME ?= meeting-assistant-worker

# GCP Secret Manager resource names (right-hand side of gcloud --set-secrets).
# Format: CONTAINER_ENV_VAR=GCP_SECRET_NAME:version  (comma-separated, no spaces)
GCP_OPENAI_SECRET ?= OPENAI_API_KEY
GCP_AUTH_KEYS_SECRET ?= meeting-assistant-api-keys
GCP_AUTH_JWT_SECRET ?= AUTH_JWT_SECRET
GCP_INTEGRATIONS_ENCRYPTION_SECRET ?= INTEGRATIONS_ENCRYPTION_KEY
GCP_SLACK_OAUTH_CLIENT_SECRET ?= SLACK_OAUTH_CLIENT_SECRET
GCP_GOOGLE_OAUTH_CLIENT_SECRET ?= GOOGLE_OAUTH_CLIENT_SECRET
GCP_AUTH_GOOGLE_LOGIN_CLIENT_SECRET ?= AUTH_GOOGLE_LOGIN_CLIENT_SECRET
GCP_DB_PASSWORD_SECRET ?= DB_PASSWORD

SLACK_PROVIDER ?= stub
GCP_SLACK_WEBHOOK_SECRET ?= SLACK_WEBHOOK_URL
GCP_SLACK_BOT_TOKEN_SECRET ?= SLACK_BOT_TOKEN
SLACK_DEFAULT_CHANNEL ?=

EMAIL_PROVIDER ?= stub
GCP_SENDGRID_SECRET ?= SENDGRID_API_KEY
EMAIL_FROM_ADDRESS ?= assistant@meeting-assistant.org
EMAIL_FROM_NAME ?= Meeting Assistant
EMAIL_DEFAULT_RECIPIENT ?=

CALENDAR_PROVIDER ?= stub
GCP_CALENDAR_SA_SECRET ?= GOOGLE_CALENDAR_SERVICE_ACCOUNT_JSON
CALENDAR_GOOGLE_CALENDAR_ID ?= primary
CALENDAR_GOOGLE_IMPERSONATE_SUBJECT ?=
CALENDAR_ASSISTANT_ORGANIZER_NAME ?= Meeting Assistant

# Phase 13 — OAuth app credentials (client IDs + redirect base are plain env, not secrets)
INTEGRATIONS_OAUTH_REDIRECT_BASE ?=
SLACK_OAUTH_CLIENT_ID ?=
GOOGLE_OAUTH_CLIENT_ID ?=

# Frontend CORS (comma-separated origins, e.g. https://your-app.web.app)
CORS_ORIGINS ?=

# Phase 15 — user login (email/password + Google Sign-In; separate from integrations OAuth)
AUTH_PASSWORD_LOGIN_ENABLED ?= true
AUTH_GOOGLE_LOGIN_ENABLED ?= false
AUTH_LOGIN_ALLOW_DEV ?= false
AUTH_GOOGLE_LOGIN_CLIENT_ID ?=
AUTH_GOOGLE_LOGIN_REDIRECT_BASE ?=

# Jira — deferred (see features.json tool-jira-live); secret name reserved for when enabled
JIRA_PROVIDER ?= stub
GCP_JIRA_API_TOKEN_SECRET ?= JIRA_API_TOKEN
JIRA_BASE_URL ?=
JIRA_USER_EMAIL ?=
JIRA_PROJECT_KEY ?=
JIRA_DEFAULT_ISSUE_TYPE ?= Task

# --- Phase 14 — Pub/Sub batch job queue (GCP production; Docker Compose keeps arq) ---
JOB_QUEUE_PROVIDER ?= arq
PUBSUB_TOPIC ?= meeting-assistant-batch-jobs
PUBSUB_PROJECT ?= $(PROJECT_ID)
PUBSUB_SUBSCRIPTION ?= meeting-assistant-batch-push
PUBSUB_PUSH_PATH ?= /internal/jobs/batch
PUBSUB_PUSH_SERVICE_ACCOUNT ?= pubsub-push@$(PROJECT_ID).iam.gserviceaccount.com
PROJECT_NUMBER ?= $(shell gcloud projects describe $(PROJECT_ID) --format='value(projectNumber)' 2>/dev/null)
DEFAULT_RUN_SA ?= $(PROJECT_NUMBER)-compute@developer.gserviceaccount.com

# ARQ polls Redis continuously (min-instances=1); Pub/Sub push wakes worker on demand (min-instances=0).
ifeq ($(JOB_QUEUE_PROVIDER),pubsub)
WORKER_MIN_INSTANCES := 0
else
WORKER_MIN_INSTANCES := 1
endif

# Optional: omit DB_PASSWORD from deploy/.env.prod and fetch from Secret Manager at deploy time
ifndef DB_PASSWORD
DB_PASSWORD := $(shell gcloud secrets versions access latest --secret=$(GCP_DB_PASSWORD_SECRET) --project=$(PROJECT_ID) 2>/dev/null)
endif

# gcloud --set-env-vars requires comma-separated KEY=VALUE pairs (spaces break DATABASE_URL).
CLOUD_RUN_ENV := MEETING_ASSISTANT_DATABASE_URL=postgresql+psycopg://$(DB_USER):$(DB_PASSWORD)@/$(DB_NAME)?host=/cloudsql/$(CLOUDSQL_INSTANCE_CONNECTION),MEETING_ASSISTANT_BATCH_PROCESSING_MODE=async,MEETING_ASSISTANT_JOB_QUEUE_PROVIDER=$(JOB_QUEUE_PROVIDER),MEETING_ASSISTANT_QUEUE_PROVIDER=redis,MEETING_ASSISTANT_REDIS_URL=$(REDIS_URL),MEETING_ASSISTANT_EMBEDDING_PROVIDER=openai,MEETING_ASSISTANT_QUERY_PROVIDER=openai,MEETING_ASSISTANT_LLM_PROVIDER=openai,MEETING_ASSISTANT_ASR_PROVIDER=openai,MEETING_ASSISTANT_ASR_UPLOAD_BACKEND=gcs,MEETING_ASSISTANT_ASR_GCS_BUCKET=$(GCS_AUDIO_BUCKET),MEETING_ASSISTANT_AUTH_ENABLED=$(AUTH_ENABLED),MEETING_ASSISTANT_LOG_JSON=true,MEETING_ASSISTANT_RATE_LIMIT_ENABLED=true,MEETING_ASSISTANT_READINESS_CHECK_REDIS=true,MEETING_ASSISTANT_SLACK_PROVIDER=$(SLACK_PROVIDER),MEETING_ASSISTANT_EMAIL_PROVIDER=$(EMAIL_PROVIDER),MEETING_ASSISTANT_CALENDAR_PROVIDER=$(CALENDAR_PROVIDER),MEETING_ASSISTANT_CALENDAR_ASSISTANT_ORGANIZER_NAME=$(CALENDAR_ASSISTANT_ORGANIZER_NAME)

ifeq ($(JOB_QUEUE_PROVIDER),pubsub)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_PUBSUB_TOPIC=$(PUBSUB_TOPIC),MEETING_ASSISTANT_PUBSUB_PROJECT=$(PUBSUB_PROJECT)
endif

PUBSUB_PUSH_AUDIENCE ?=

CLOUD_RUN_SECRETS := MEETING_ASSISTANT_LLM_OPENAI_API_KEY=$(GCP_OPENAI_SECRET):latest,MEETING_ASSISTANT_EMBEDDING_OPENAI_API_KEY=$(GCP_OPENAI_SECRET):latest,MEETING_ASSISTANT_ASR_OPENAI_API_KEY=$(GCP_OPENAI_SECRET):latest,MEETING_ASSISTANT_INTEGRATIONS_ENCRYPTION_KEY=$(GCP_INTEGRATIONS_ENCRYPTION_SECRET):latest,MEETING_ASSISTANT_SLACK_OAUTH_CLIENT_SECRET=$(GCP_SLACK_OAUTH_CLIENT_SECRET):latest,MEETING_ASSISTANT_GOOGLE_OAUTH_CLIENT_SECRET=$(GCP_GOOGLE_OAUTH_CLIENT_SECRET):latest

ifeq ($(AUTH_ENABLED),true)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_AUTH_MODE=api_key,MEETING_ASSISTANT_AUTH_PASSWORD_LOGIN_ENABLED=$(AUTH_PASSWORD_LOGIN_ENABLED),MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_ENABLED=$(AUTH_GOOGLE_LOGIN_ENABLED),MEETING_ASSISTANT_AUTH_LOGIN_ALLOW_DEV=$(AUTH_LOGIN_ALLOW_DEV)
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_AUTH_API_KEYS=$(GCP_AUTH_KEYS_SECRET):latest,MEETING_ASSISTANT_AUTH_JWT_SECRET=$(GCP_AUTH_JWT_SECRET):latest
ifeq ($(AUTH_GOOGLE_LOGIN_ENABLED),true)
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_CLIENT_SECRET=$(GCP_AUTH_GOOGLE_LOGIN_CLIENT_SECRET):latest
endif
endif

ifneq ($(AUTH_GOOGLE_LOGIN_CLIENT_ID),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_CLIENT_ID=$(AUTH_GOOGLE_LOGIN_CLIENT_ID)
endif

ifneq ($(AUTH_GOOGLE_LOGIN_REDIRECT_BASE),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_REDIRECT_BASE=$(AUTH_GOOGLE_LOGIN_REDIRECT_BASE)
endif

ifneq ($(INTEGRATIONS_OAUTH_REDIRECT_BASE),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_INTEGRATIONS_OAUTH_REDIRECT_BASE=$(INTEGRATIONS_OAUTH_REDIRECT_BASE)
endif

ifneq ($(SLACK_OAUTH_CLIENT_ID),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_SLACK_OAUTH_CLIENT_ID=$(SLACK_OAUTH_CLIENT_ID)
endif

ifneq ($(GOOGLE_OAUTH_CLIENT_ID),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_GOOGLE_OAUTH_CLIENT_ID=$(GOOGLE_OAUTH_CLIENT_ID)
endif

ifneq ($(CORS_ORIGINS),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_CORS_ORIGINS=$(CORS_ORIGINS)
endif

ifeq ($(SLACK_PROVIDER),webhook)
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_SLACK_WEBHOOK_URL=$(GCP_SLACK_WEBHOOK_SECRET):latest
endif

ifeq ($(SLACK_PROVIDER),api)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_SLACK_DEFAULT_CHANNEL=$(SLACK_DEFAULT_CHANNEL)
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_SLACK_BOT_TOKEN=$(GCP_SLACK_BOT_TOKEN_SECRET):latest
endif

ifeq ($(EMAIL_PROVIDER),sendgrid)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_EMAIL_FROM_ADDRESS=$(EMAIL_FROM_ADDRESS),MEETING_ASSISTANT_EMAIL_FROM_NAME=$(EMAIL_FROM_NAME),MEETING_ASSISTANT_EMAIL_DEFAULT_RECIPIENT=$(EMAIL_DEFAULT_RECIPIENT)
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_EMAIL_SENDGRID_API_KEY=$(GCP_SENDGRID_SECRET):latest
endif

ifeq ($(CALENDAR_PROVIDER),google)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_CALENDAR_GOOGLE_CALENDAR_ID=$(CALENDAR_GOOGLE_CALENDAR_ID)
ifneq ($(CALENDAR_GOOGLE_IMPERSONATE_SUBJECT),)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_CALENDAR_GOOGLE_IMPERSONATE_SUBJECT=$(CALENDAR_GOOGLE_IMPERSONATE_SUBJECT)
endif
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_CALENDAR_GOOGLE_SERVICE_ACCOUNT_JSON=$(GCP_CALENDAR_SA_SECRET):latest
endif

ifeq ($(JIRA_PROVIDER),rest)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_JIRA_BASE_URL=$(JIRA_BASE_URL),MEETING_ASSISTANT_JIRA_USER_EMAIL=$(JIRA_USER_EMAIL),MEETING_ASSISTANT_JIRA_PROJECT_KEY=$(JIRA_PROJECT_KEY),MEETING_ASSISTANT_JIRA_DEFAULT_ISSUE_TYPE=$(JIRA_DEFAULT_ISSUE_TYPE)
CLOUD_RUN_SECRETS := $(CLOUD_RUN_SECRETS),MEETING_ASSISTANT_JIRA_API_TOKEN=$(GCP_JIRA_API_TOKEN_SECRET):latest
endif

ifeq ($(OTEL_ENABLED),true)
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_OTEL_ENABLED=true,MEETING_ASSISTANT_OTEL_SERVICE_NAME=$(OTEL_SERVICE_NAME),MEETING_ASSISTANT_OTEL_EXPORTER_ENDPOINT=$(OTEL_EXPORTER_ENDPOINT)
CLOUD_RUN_WORKER_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_OTEL_SERVICE_NAME=$(OTEL_WORKER_SERVICE_NAME)
else
CLOUD_RUN_WORKER_ENV := $(CLOUD_RUN_ENV)
endif

ifeq ($(JOB_QUEUE_PROVIDER),pubsub)
ifneq ($(PUBSUB_PUSH_AUDIENCE),)
CLOUD_RUN_WORKER_ENV := $(CLOUD_RUN_WORKER_ENV),MEETING_ASSISTANT_PUBSUB_PUSH_AUDIENCE=$(PUBSUB_PUSH_AUDIENCE)
endif
CLOUD_RUN_ENV := $(CLOUD_RUN_ENV),MEETING_ASSISTANT_READINESS_CHECK_WORKER=false
CLOUD_RUN_WORKER_ENV := $(CLOUD_RUN_WORKER_ENV),MEETING_ASSISTANT_READINESS_CHECK_WORKER=false,MEETING_ASSISTANT_READINESS_CHECK_REDIS=false
endif

.PHONY: deploy-api
deploy-api: docker-push
	gcloud run deploy $(SERVICE_API) \
		--project=$(PROJECT_ID) \
		--region=$(REGION) \
		--image=$(IMAGE_URI) \
		--platform=managed \
		--allow-unauthenticated \
		--port=8080 \
		--cpu=2 \
		--memory=2Gi \
		--timeout=300 \
		--max-instances=10 \
		--concurrency=40 \
		--add-cloudsql-instances=$(CLOUDSQL_INSTANCE_CONNECTION) \
		$(if $(VPC_CONNECTOR),--vpc-connector=$(VPC_CONNECTOR),) \
		$(if $(VPC_CONNECTOR),--vpc-egress=private-ranges-only,) \
		--set-env-vars="$(CLOUD_RUN_ENV)" \
		--set-secrets="$(CLOUD_RUN_SECRETS)"

.PHONY: deploy-worker
deploy-worker: docker-push
	gcloud run deploy $(SERVICE_WORKER) \
		--project=$(PROJECT_ID) \
		--region=$(REGION) \
		--image=$(IMAGE_URI) \
		--platform=managed \
		--no-allow-unauthenticated \
		--port=8080 \
		--cpu=2 \
		--memory=4Gi \
		--timeout=3600 \
		--min-instances=$(WORKER_MIN_INSTANCES) \
		--max-instances=5 \
		--no-cpu-throttling \
		--command=/app/scripts/cloudrun_worker_entrypoint.sh \
		--add-cloudsql-instances=$(CLOUDSQL_INSTANCE_CONNECTION) \
		$(if $(VPC_CONNECTOR),--vpc-connector=$(VPC_CONNECTOR),) \
		$(if $(VPC_CONNECTOR),--vpc-egress=private-ranges-only,) \
		--set-env-vars="$(CLOUD_RUN_WORKER_ENV),MEETING_ASSISTANT_TOOL_EXECUTION_BACKOFF_MODE=background" \
		--set-secrets="$(CLOUD_RUN_SECRETS)"

.PHONY: deploy
deploy: deploy-api deploy-worker

# Simpler first deploy: one Cloud Run service, in-process job queue (no Redis/worker).
BOOTSTRAP_ENV := MEETING_ASSISTANT_DATABASE_URL=postgresql+psycopg://$(DB_USER):$(DB_PASSWORD)@/$(DB_NAME)?host=/cloudsql/$(CLOUDSQL_INSTANCE_CONNECTION),MEETING_ASSISTANT_BATCH_PROCESSING_MODE=async,MEETING_ASSISTANT_JOB_QUEUE_PROVIDER=inprocess,MEETING_ASSISTANT_QUEUE_PROVIDER=memory,MEETING_ASSISTANT_EMBEDDING_PROVIDER=openai,MEETING_ASSISTANT_QUERY_PROVIDER=openai,MEETING_ASSISTANT_LLM_PROVIDER=openai,MEETING_ASSISTANT_ASR_PROVIDER=openai,MEETING_ASSISTANT_ASR_UPLOAD_BACKEND=gcs,MEETING_ASSISTANT_ASR_GCS_BUCKET=$(GCS_AUDIO_BUCKET),MEETING_ASSISTANT_AUTH_ENABLED=$(AUTH_ENABLED),MEETING_ASSISTANT_LOG_JSON=true,MEETING_ASSISTANT_RATE_LIMIT_ENABLED=true,MEETING_ASSISTANT_READINESS_CHECK_REDIS=false

.PHONY: deploy-bootstrap
deploy-bootstrap: docker-push
	gcloud run deploy $(SERVICE_API) \
		--project=$(PROJECT_ID) \
		--region=$(REGION) \
		--image=$(IMAGE_URI) \
		--platform=managed \
		--allow-unauthenticated \
		--port=8080 \
		--cpu=2 \
		--memory=4Gi \
		--timeout=3600 \
		--min-instances=1 \
		--max-instances=2 \
		--concurrency=20 \
		--add-cloudsql-instances=$(CLOUDSQL_INSTANCE_CONNECTION) \
		--set-env-vars="$(BOOTSTRAP_ENV)" \
		--set-secrets="$(CLOUD_RUN_SECRETS)"

.PHONY: smoke
smoke:
	@URL=$$(gcloud run services describe $(SERVICE_API) --project=$(PROJECT_ID) --region=$(REGION) --format='value(status.url)'); \
	echo "API URL: $$URL"; \
	curl -fsS "$$URL/health"; echo; \
	curl -fsS "$$URL/ready" | python3 -m json.tool

# --- Pub/Sub infrastructure (Phase 14) ---
.PHONY: pubsub-push-sa-create
pubsub-push-sa-create:
	gcloud config set project $(PROJECT_ID)
	gcloud iam service-accounts describe $(PUBSUB_PUSH_SERVICE_ACCOUNT) --project=$(PROJECT_ID) >/dev/null 2>&1 \
	|| gcloud iam service-accounts create pubsub-push \
		--project=$(PROJECT_ID) \
		--display-name="Pub/Sub push invoker for Meeting Assistant worker"

.PHONY: pubsub-topic-create
pubsub-topic-create:
	gcloud config set project $(PUBSUB_PROJECT)
	gcloud pubsub topics describe $(PUBSUB_TOPIC) --project=$(PUBSUB_PROJECT) >/dev/null 2>&1 \
	|| gcloud pubsub topics create $(PUBSUB_TOPIC) --project=$(PUBSUB_PROJECT)

.PHONY: pubsub-iam
pubsub-iam: pubsub-push-sa-create pubsub-topic-create
	@API_SA=$$(gcloud run services describe $(SERVICE_API) \
		--project=$(PROJECT_ID) --region=$(REGION) \
		--format='value(spec.template.spec.serviceAccountName)' 2>/dev/null); \
	API_SA=$${API_SA:-$(DEFAULT_RUN_SA)}; \
	echo "Granting roles/pubsub.publisher on $(PUBSUB_TOPIC) to $$API_SA"; \
	gcloud pubsub topics add-iam-policy-binding $(PUBSUB_TOPIC) \
		--project=$(PUBSUB_PROJECT) \
		--member="serviceAccount:$$API_SA" \
		--role="roles/pubsub.publisher" \
		--quiet
	@if gcloud run services describe $(SERVICE_WORKER) \
		--project=$(PROJECT_ID) --region=$(REGION) >/dev/null 2>&1; then \
		echo "Granting roles/run.invoker on $(SERVICE_WORKER) to $(PUBSUB_PUSH_SERVICE_ACCOUNT)"; \
		gcloud run services add-iam-policy-binding $(SERVICE_WORKER) \
			--project=$(PROJECT_ID) --region=$(REGION) \
			--member="serviceAccount:$(PUBSUB_PUSH_SERVICE_ACCOUNT)" \
			--role="roles/run.invoker" \
			--quiet; \
	else \
		echo "Worker not deployed yet — run make deploy-worker then re-run make pubsub-iam for run.invoker"; \
	fi

.PHONY: pubsub-subscription-create
pubsub-subscription-create: pubsub-topic-create pubsub-push-sa-create
	@WORKER_URL=$$(gcloud run services describe $(SERVICE_WORKER) \
		--project=$(PROJECT_ID) --region=$(REGION) \
		--format='value(status.url)' 2>/dev/null); \
	if [ -z "$$WORKER_URL" ]; then \
		echo "Deploy worker first: make deploy-worker JOB_QUEUE_PROVIDER=pubsub"; exit 1; fi; \
	PUSH_ENDPOINT="$$WORKER_URL$(PUBSUB_PUSH_PATH)"; \
	AUDIENCE="$${PUBSUB_PUSH_AUDIENCE:-$$PUSH_ENDPOINT}"; \
	echo "Push endpoint: $$PUSH_ENDPOINT"; \
	echo "Push token audience: $$AUDIENCE"; \
	if gcloud pubsub subscriptions describe $(PUBSUB_SUBSCRIPTION) --project=$(PUBSUB_PROJECT) >/dev/null 2>&1; then \
		gcloud pubsub subscriptions update $(PUBSUB_SUBSCRIPTION) \
			--project=$(PUBSUB_PROJECT) \
			--push-endpoint="$$PUSH_ENDPOINT" \
			--push-auth-service-account="$(PUBSUB_PUSH_SERVICE_ACCOUNT)" \
			--push-auth-token-audience="$$AUDIENCE" \
			--expiration-period=never \
			--ack-deadline=600 \
			--message-retention-duration=7d \
			--min-retry-delay=10s \
			--max-retry-delay=600s; \
	else \
		gcloud pubsub subscriptions create $(PUBSUB_SUBSCRIPTION) \
			--project=$(PUBSUB_PROJECT) \
			--topic=$(PUBSUB_TOPIC) \
			--push-endpoint="$$PUSH_ENDPOINT" \
			--push-auth-service-account="$(PUBSUB_PUSH_SERVICE_ACCOUNT)" \
			--push-auth-token-audience="$$AUDIENCE" \
			--ack-deadline=600 \
			--message-retention-duration=7d \
			--min-retry-delay=10s \
			--max-retry-delay=600s \
			--expiration-period=never; \
	fi

.PHONY: pubsub-setup
pubsub-setup: pubsub-iam pubsub-subscription-create
	@echo "Pub/Sub infra ready. Set JOB_QUEUE_PROVIDER=pubsub and deploy-api after job-queue-pubsub code is merged."

# --- Local Docker Compose (production-shaped dev without GCP) ---
COMPOSE_ENV_FILE ?= .env.compose

.PHONY: compose-config
compose-config:
	@test -f $(COMPOSE_ENV_FILE) || cp .env.compose.example $(COMPOSE_ENV_FILE)
	docker compose --env-file $(COMPOSE_ENV_FILE) config -q

.PHONY: compose-up
compose-up:
	@test -f $(COMPOSE_ENV_FILE) || cp .env.compose.example $(COMPOSE_ENV_FILE)
	docker compose --env-file $(COMPOSE_ENV_FILE) up --build -d

.PHONY: compose-down
compose-down:
	docker compose --env-file $(COMPOSE_ENV_FILE) down

.PHONY: compose-smoke
compose-smoke:
	@echo "API health:"; curl -fsS http://127.0.0.1:$${COMPOSE_API_PORT:-8000}/health; echo
	@echo "API ready:"; curl -fsS http://127.0.0.1:$${COMPOSE_API_PORT:-8000}/ready | python3 -m json.tool
	@echo "Worker health:"; curl -fsS http://127.0.0.1:$${COMPOSE_WORKER_PORT:-8081}/health; echo
