# Runbook — Dify + Dynatrace OTel Bridge

Guia operacional para levantar o bridge de telemetria (`dynatrace-otel-bridge`)
ao lado de uma instalação self-hosted da Dify numa VM.

## 1. Prerequisites

- A GCP project with permission to create VMs and firewall rules.
- A Dynatrace tenant (SaaS).
- A Dynatrace API Token with **ingest** scopes:
  - `openTelemetryTrace.ingest`
  - `metrics.ingest`
  - `logs.ingest`

  These are different from the `*.read` scopes used elsewhere; a read-only
  token will not work here.

## 2. Provision a new VM

See [GCP-SETUP.md](GCP-SETUP.md) for machine specs, firewall rules, and
Docker/Compose/git installation. Come back here once the VM is reachable
over SSH and `docker compose version` works.

## 3. Deploy

This assumes the official Dify self-hosted installation is already present
on the VM (its `docker/` directory, with `docker-compose.yaml` and `.env`).

1. Clone/pull this repo onto the VM.

2. Configure and start the collector first — the shared Docker network
   (`dify-otel-net`) that Dify's `api`/`worker` depend on is created by
   this stack, so it must come up before Dify's `docker compose up`:

   ```bash
   cd examples/docker-compose
   cp .env.example .env
   #   edit .env: DT_OTLP_ENDPOINT, DT_API_TOKEN (+ optional DEPLOYMENT_ENVIRONMENT)
   docker compose up -d
   ```

3. Apply the Dify override. Copy this repo's
   [docker-compose.override.dify-example.yaml](docker-compose.override.dify-example.yaml)
   into the Dify installation's `docker/` directory, renaming it:

   ```bash
   cp docker-compose.override.dify-example.yaml <dify-install>/docker/docker-compose.override.yaml
   ```

4. Bring up (or restart) the Dify stack so the override is applied:

   ```bash
   cd <dify-install>/docker
   docker compose up -d
   ```

5. Start the Dify workflow telemetry exporter from this repo:

   ```bash
   cd <path-to-this-repo>
   docker compose -f docker-compose.workflow-exporter.yaml up -d --build
   ```

   The exporter listens on host port `8088` and forwards incoming Dify API
   calls to `http://api:5001` over `dify-otel-net`.

## 4. Quick checks

Run these from the VM after step 3.

**Dify is up:**
```bash
cd <dify-install>/docker
docker compose ps
```
All services should show `Up` (or `running`/`healthy`, depending on Compose version).

**`web` binds on all interfaces (0.0.0.0:3000), not a single network's IP:**
```bash
docker compose exec web sh -c "ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null" | grep 3000
```
Expect `0.0.0.0:3000` (or `:::3000`) in the output — not a specific container IP.

**`api` resolves `otel-collector` by DNS name (shared `dify-otel-net`):**
```bash
docker compose exec api getent hosts otel-collector
```
Expect an IP to be printed. If `getent` isn't available in the image, use:
```bash
docker compose exec api python -c "import socket; print(socket.gethostbyname('otel-collector'))"
```

**Collector is healthy:**
```bash
cd <path-to-this-repo>/examples/docker-compose
curl -sf http://localhost:13133 && echo " OK"
```

**Collector is exporting without errors:**
```bash
docker compose logs --tail 100 otel-collector | grep -i "Exporting failed"
```
No output = no export failures. If this prints lines, see step 5.

**Workflow exporter is reachable:**
```bash
curl -sf http://localhost:8088/healthz
```

**Node-level telemetry path is used:**
Call workflows through the exporter, not directly through Dify:
```bash
curl --request POST \
  --url http://localhost:8088/v1/workflows/run \
  --header 'Authorization: Bearer <dify-app-api-key>' \
  --header 'Content-Type: application/json' \
  --data '{"inputs":{},"response_mode":"streaming","user":"otel-test"}'
```

Use `response_mode=streaming` for workflow/node spans. Blocking calls can only
produce a run-level span.

## 5. Troubleshooting

For anything beyond the quick checks above (collector crash loops, health
check failures, 401/403/404 from Dynatrace, no data arriving, etc.), follow
[docs/troubleshooting.md](docs/troubleshooting.md) — it already covers these
cases in detail and isn't duplicated here.
