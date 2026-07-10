# dynatrace-otel-bridge

An OpenTelemetry conformance bridge for Dify GenAI telemetry. It runs an OTel
Collector that ingests Dify's native (but non-conformant) OTLP output,
normalizes it to the official **OTel GenAI Semantic Conventions**, and forwards
it to an observability backend.

The pipeline is **backend-agnostic by design** and **validated against Dynatrace
AI Observability**. Because the conformance layer emits standard OTel GenAI
telemetry, any conformant backend (Dynatrace, Datadog, Grafana, Honeycomb, …)
can ingest it; only the exporter and two enrichment processors are
Dynatrace-specific. See [Portability](#portability).

This repo is the **write/emit path** (telemetry going into the backend). The
read path — querying backend problems and metrics from apps — lives in a
separate repo (the Dify plugin).

## How it works

```
  Dify (ENABLE_OTEL)  ──OTLP──►  OTel Collector  ──OTLP──►  Backend
                        :4318    (conformance)     HTTPS    (Dynatrace, validated)
```

Dify emits node-level spans natively from its GraphEngine `ObservabilityLayer`,
covering every invocation path (Studio, WebApp, Service API, Debugger). The
Collector's conformance processors fix the native dialect — array-vs-string
`finish_reasons`, clean provider names, legacy attribute promotion, namespace
hygiene — and two enrichment processors populate fields the backend's LLM
observability app expects. The result: node spans, token usage, cost, provider,
and model counts render correctly downstream.

For the full pipeline breakdown (each processor, the gap it fixes, and its
portability), see [RUNBOOK.md](RUNBOOK.md#telemetry-pipeline).

## Components

- `infra/collector/otelcol-config.yaml` — Collector config: OTLP receivers
  (gRPC + HTTP), conformance/enrichment `transform` + `filter` processors,
  `otlphttp` exporter, `health_check` extension.
- `examples/docker-compose/` — minimal test environment (Collector only),
  parameterized via `.env`.
- `docker-compose.override.dify-example.yaml` — example override that points a
  self-hosted Dify stack at the Collector (`ENABLE_OTEL`).
- `legacy/` — Track B (exporter/proxy), retired; see
  [`legacy/README.md`](legacy/README.md).

## Requirements

- Docker + Docker Compose.
- A backend that ingests OTLP. Reference target: a Dynatrace tenant (SaaS or
  Managed).
- For Dynatrace: an API Token with ingest scopes `openTelemetryTrace.ingest`,
  `metrics.ingest`, `logs.ingest` (different from the `*.read` scopes).

## Quickstart

```bash
cd examples/docker-compose

# 1. Configure credentials (no tokens in git — .env is ignored)
cp .env.example .env
#    edit .env: DT_OTLP_ENDPOINT, DT_API_TOKEN (+ optional DEPLOYMENT_ENVIRONMENT)

# 2. Start the Collector
docker compose up -d

# 3. Check health and logs
curl -sf http://localhost:13133 && echo " OK"
docker compose logs -f otel-collector
```

Point any OTel-instrumented app (including Dify, via the override) at the
Collector:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # or :4317 for gRPC
```

Exposed ports: 4317 (OTLP gRPC), 4318 (OTLP HTTP), 13133 (health_check).

For a full VM deployment alongside Dify, see [RUNBOOK.md](RUNBOOK.md).

## Portability

The receiver, conformance processors, and OTLP transport are backend-agnostic.
To target a backend other than Dynatrace, replace the `otlphttp/dynatrace`
exporter with your backend's OTLP endpoint and auth, and review the two
Dynatrace-motivated enrichment processors
([details](RUNBOOK.md#backend-specific-dynatrace-ai-observability-enrichment)).

**Validation status:** validated against Dynatrace AI Observability. Other
backends are supported *by design* but not yet validated. Validating the
backend-agnostic path against Datadog LLM Observability and Grafana/Tempo is on
the roadmap.

## Notes

- `DT_OTLP_ENDPOINT` must end with `/api/v2/otlp` — the `otlphttp` exporter
  appends `/v1/traces`, `/v1/metrics`, `/v1/logs`.
- Dynatrace auth uses the `Authorization: Api-Token <token>` header.
- The config includes a `debug` exporter alongside `otlphttp`, useful for
  inspecting the pipeline locally; remove it in production.

For troubleshooting, see [docs/troubleshooting.md](docs/troubleshooting.md).
