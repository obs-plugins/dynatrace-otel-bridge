# dynatrace-otel-bridge

OpenTelemetry → Dynatrace telemetry bridge. Spins up an OTel Collector that receives traces, metrics, and logs via OTLP and forwards them to a Dynatrace tenant. It is application‑agnostic: any app instrumented with OTel (Dify or otherwise) can send data to it.

This repo is the write/emit path (telemetry going into Dynatrace).
The read path — querying Dynatrace problems and metrics from apps — lives in a different repo (the Dify plugin).

## Components

- `infra/collector/otelcol-config.yaml` — Collector config: OTLP receivers (gRPC + HTTP), `resource`/`batch` processors, `otlphttp` exporter to Dynatrace, `health_check` extension.
- `exporter/` — Dify Workflow SSE proxy/exporter. It forwards Workflow API calls to Dify, parses streaming workflow/node events, and emits OpenTelemetry spans.
- `examples/docker-compose/` — minimal test environment (Collector only), parameterized via `.env`.
- `docker-compose.workflow-exporter.yaml` — compose service for the Dify Workflow OTel exporter, attached to the shared `dify-otel-net` network.

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

The collector only forwards telemetry. To extract Dify workflow/node details,
run the workflow exporter after the collector and the Dify stack are on the
shared `dify-otel-net` network:

```bash
docker compose -f docker-compose.workflow-exporter.yaml up -d --build
```

Then call the exporter instead of calling Dify directly:

```bash
curl --request POST \
  --url http://<vm-host>:8088/v1/workflows/run \
  --header 'Authorization: Bearer <dify-app-api-key>' \
  --header 'Content-Type: application/json' \
  --data '{
    "inputs": {"query": "hello"},
    "response_mode": "streaming",
    "user": "user-123"
  }'
```

The exporter proxies the response back unchanged while converting Dify SSE
events such as `workflow_finished`, `node_started`, and `node_finished` into
OpenTelemetry spans. For node-level telemetry, use `response_mode=streaming`;
blocking calls can only produce run-level spans from the final response.

Setting `OTEL_*` environment variables on Dify containers is still useful for
native or auto-instrumented telemetry, but it does not by itself create
workflow/node semantic spans. The exporter observes Dify's workflow event
stream, which is where those node-level events are exposed.

By default, prompts, inputs, and outputs are not copied into span attributes.
Set `DIFY_OTEL_CAPTURE_CONTENT=true` only after reviewing privacy and data
retention requirements.

## Notes

- `DT_OTLP_ENDPOINT` must end with `/api/v2/otlp` — the `otlphttp` exporter appends `/v1/traces`, `/v1/metrics`, `/v1/logs`.
- Dynatrace auth uses the `Authorization: Api-Token <token>` header.
- The config includes a `debug` exporter in addition to `otlphttp`, useful for inspecting the pipeline locally; you can remove it in production.

For troubleshooting, see docs/troubleshooting.md.