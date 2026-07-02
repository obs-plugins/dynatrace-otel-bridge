# dynatrace-otel-bridge

Ponte de telemetria **OpenTelemetry → Dynatrace**. Sobe um **OTel Collector** que recebe
traces, métricas e logs via OTLP e os reencaminha para um tenant Dynatrace. É agnóstico à
aplicação: **qualquer** app instrumentada com OTel (Dify ou outra) pode apontar para ele.

> Este repo é o *write/emit path* (telemetria a entrar no Dynatrace). O *read path* — consultar
> problemas e métricas do Dynatrace a partir de apps — vive noutro repo (plugin Dify).

## Componentes

- `infra/collector/otelcol-config.yaml` — config do Collector: receivers OTLP (gRPC+HTTP),
  processors `resource`/`batch`, exporter `otlphttp` para Dynatrace, extensão `health_check`.
- `examples/docker-compose/` — ambiente de teste mínimo (só o Collector), parametrizado por `.env`.

## Requisitos

- Docker + Docker Compose.
- Um tenant **Dynatrace** (SaaS ou Managed).
- Um **API Token** com scopes de **ingest**: `metrics.ingest`, `logs.ingest`,
  `openTelemetryTrace.ingest`. (São diferentes dos scopes de leitura `*.read`.)

## Quickstart

```bash
cd examples/docker-compose

# 1. Configurar credenciais (sem tokens no git — .env é ignorado)
cp .env.example .env
#    editar .env: DT_OTLP_ENDPOINT, DT_API_TOKEN (+ opcional DEPLOYMENT_ENVIRONMENT)

# 2. Subir o Collector
docker compose up -d

# 3. Verificar saúde e logs
curl -sf http://localhost:13133 && echo " OK"
docker compose logs -f otel-collector
```

Apontar qualquer app OTel para o Collector:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # ou :4317 para gRPC
```

Portas expostas: **4317** (OTLP gRPC), **4318** (OTLP HTTP), **13133** (health_check).

Confirmar depois a ingestão no Dynatrace (Distributed Traces / Metrics do teu env-id). O resource
attribute `deployment.environment` reflete o valor de `DEPLOYMENT_ENVIRONMENT`.

## Notas

- `DT_OTLP_ENDPOINT` deve terminar em `/api/v2/otlp` — o exporter `otlphttp` acrescenta
  `/v1/traces`, `/v1/metrics`, `/v1/logs`.
- Auth Dynatrace usa o header `Authorization: Api-Token <token>`.
- O config inclui um exporter `debug` além do `otlphttp`, útil para inspecionar o pipeline
  localmente; podes removê-lo em produção.
