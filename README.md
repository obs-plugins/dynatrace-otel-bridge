# dynatrace-otel-bridge

OpenTelemetry → Dynatrace telemetry bridge. Spins up an OTel Collector that receives traces, metrics, and logs via OTLP and forwards them to a Dynatrace tenant. It is application‑agnostic: any app instrumented with OTel (Dify or otherwise) can send data to it.

This repo is the write/emit path (telemetry going into Dynatrace).
The read path — querying Dynatrace problems and metrics from apps — lives in a different repo (the Dify plugin).

## Components

- `infra/collector/otelcol-config.yaml` — Collector config: OTLP receivers (gRPC + HTTP), `resource`/`batch` processors, `otlphttp` exporter to Dynatrace, `health_check` extension.
- `examples/docker-compose/` — minimal test environment (Collector only), parameterized via `.env`.
- `legacy/` — Track B (exporter/proxy), retired; see legacy/README.md.

## Requirements

- Docker + Docker Compose.
- A Dynatrace tenant (SaaS or Managed).
- An API Token with ingest scopes: `metrics.ingest`, `logs.ingest`, `openTelemetryTrace.ingest`. (These are different from the `*.read` scopes.)

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

Point any OTel‑instrumented app to the Collector:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # or :4317 for gRPC
```

Exposed ports: 4317 (OTLP gRPC), 4318 (OTLP HTTP), 13133 (health_check).

Then confirm ingestion in Dynatrace (Distributed Traces / Metrics for your environment).
The deployment.environment resource attribute reflects the value of DEPLOYMENT_ENVIRONMENT.

## Dify workflow/node telemetry

Dify workflow/node telemetry is produced natively by Dify (Track A): with
`ENABLE_OTEL` pointing the Dify stack at `otel-collector:4318`, the collector's
OTTL conformance processors normalize the native GenAI attributes and forward
them to Dynatrace, where the AI Observability app populates node spans, tokens,
provider, and models.

The former Track B (an SSE reverse-proxy/exporter on port 8088) was retired as
redundant once Track A was validated. It is archived under `legacy/` — see
`legacy/README.md` for what it was and why.

## Notes

- `DT_OTLP_ENDPOINT` must end with `/api/v2/otlp` — the `otlphttp` exporter appends `/v1/traces`, `/v1/metrics`, `/v1/logs`.
- Dynatrace auth uses the `Authorization: Api-Token <token>` header.
- The config includes a `debug` exporter in addition to `otlphttp`, useful for inspecting the pipeline locally; you can remove it in production.

For troubleshooting, see docs/troubleshooting.md.