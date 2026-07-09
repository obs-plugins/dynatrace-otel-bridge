# Troubleshooting

This guide helps you isolate issues in the bridge telemetry chain:

```text
app  ──OTLP──▶  Collector  ──OTLP/HTTP──▶  Dynatrace
             (4317 gRPC /              (otlphttp exporter:
              4318 HTTP)                DT_OTLP_ENDPOINT + DT_API_TOKEN)
```

Always diagnose from the inside out, in this order:

1. The Collector starts and stays up.
2. The Collector is healthy (health check responds).
3. The Collector talks to Dynatrace (exports without HTTP errors).
4. The app sends telemetry to the Collector.

Skipping steps usually means you end up debugging in the wrong place. Follow the order of the sections below.

## Before you start

Quick checklist before any troubleshooting:

- `.env` present and filled in — copied from `.env.example` with all required variables set:
  - `DT_OTLP_ENDPOINT` — OTLP/HTTP endpoint of your Dynatrace tenant.
  - `DT_API_TOKEN` — token with the required OTLP ingest scope.
- Host ports are free — 4317 (OTLP gRPC), 4318 (OTLP HTTP), and 13133 (health check).

Basic commands (run from the compose folder, for example `examples/docker-compose/`):

```bash
docker compose up -d           # start in background
docker compose ps              # check container status
docker compose logs -f otel-collector   # follow Collector logs
```

If `.env` is not filled in, the Collector may not even start (see next section).

## Collector does not start (crash / restart loop)

### Symptom

- `docker compose up` fails immediately, or the container keeps going to `Restarting` / `Exited` instead of `Up`.
- `docker compose ps` shows a state different from `running` / `Up`.

### Possible causes

- Syntax or indentation error in `otelcol-config.yaml` (invalid YAML).
- Mis‑referenced pipeline — a receiver / processor / exporter is listed in `service.pipelines` but not defined above.
- Missing `.env` → required variable ends up empty and the config cannot expand it.
- Host port already in use (4317, 4318 or 13133) → bind failure.
- Collector image/tag does not exist or was not pulled.

### How to check & fix

```bash
docker compose ps                               # status and restart count
docker compose logs otel-collector --tail=50    # first error line usually shows the cause
```

The first error line from the Collector is usually explicit: `error decoding 'exporters'`, `cannot bind to address`, `undefined receiver`, and so on.

Validate the config without starting the full service:

```bash
docker compose run --rm otel-collector validate --config /etc/otelcol-contrib/config.yaml
```

(the subcommand may be `otelcol validate`, depending on the distro/image).

Check if any port is already in use on the host:

```bash
lsof -i :4317 ; lsof -i :4318 ; lsof -i :13133
```

Confirm that `.env` exists and is filled in (see [Before you start](#before-you-start)).

## Health check fails (`curl http://localhost:13133`)

### Symptom

`curl http://localhost:13133` returns connection refused, times out, or responds with a status other than 200.

### Possible causes

- `health_check` extension is not enabled in `otelcol-config.yaml` (missing from `service.extensions`).
- Container is still starting up or has already crashed (ties back to the previous section).
- Port 13133 is not mapped in `docker-compose.yaml`, or is mapped to a different host port.
- You are testing from a different machine/network — the mapping is only for localhost.

### How to check & fix

```bash
docker compose ps                 # is the container actually Up?
curl -v http://localhost:13133    # distinguish "refused" from an HTTP response
```

If the container is not `Up`, go back to [Collector does not start](#collector-does-not-start-crash--restart-loop).

Connection refused = nothing is listening on that port; non‑200 HTTP response = service is up but health is reporting a problem.

Confirm that `health_check` is listed under `service::extensions` in the config and that `13133:13133` is present in the compose file.

Test from inside the container (isolates app vs host port mapping):

```bash
docker compose exec otel-collector wget -qO- localhost:13133
```

## Collector starts but Dynatrace receives no data

### Symptom

The Collector is `Up` and the health check returns 200, but no data shows up in Dynatrace. Collector logs show `otlphttp` exporter errors with an HTTP status code.

Cross‑check — find the status code returned by the endpoint:

```bash
docker compose logs otel-collector | grep -Ei "otlphttp|export|status|permanent"
```

### 401 / 403 — authentication

#### Possible causes

- `DT_API_TOKEN` invalid or expired.
- Token is missing the required OTLP ingest scope.
- Malformed authorization header.

#### How to check & fix

```bash
docker compose exec otel-collector printenv DT_API_TOKEN   # confirm it is set
```

Confirm that the token exists inside the container (not only in the host `.env`).

Verify that the token has the required OTLP ingest scope in Dynatrace.

Call the endpoint directly, sending the token header, to see which status code it returns:

```bash
curl -v -X POST "$DT_OTLP_ENDPOINT" \
  -H "Authorization: Api-Token dt0c01.XXXX" \
  -H "Content-Type: application/x-protobuf"
```

### 404 — wrong endpoint

#### Possible causes

- `DT_OTLP_ENDPOINT` has an incorrect host or path (missing the proper OTLP path, extra or missing `/`, or wrong tenant).

#### How to check & fix

```bash
docker compose exec otel-collector printenv DT_OTLP_ENDPOINT
```

Compare the value with the expected Dynatrace OTLP endpoint format.

Run `curl -v "$DT_OTLP_ENDPOINT"` to see if the path exists (404 vs some other response).

### 5xx / timeouts / connection issues

#### Possible causes

- Temporary Dynatrace backend unavailability.
- Network, proxy, or firewall issues blocking HTTPS egress.
- DNS failures inside the container.

#### How to check & fix

```bash
docker compose exec otel-collector wget -qO- https://<endpoint-host>   # DNS + connectivity
```

Ensure DNS resolution and connectivity from inside the container to the endpoint host.

Confirm that HTTPS egress is not blocked by a proxy or firewall.

Note: the `otlphttp` exporter retries with backoff — transient 5xx errors may recover on their own; 4xx marked as permanent will not recover and data is dropped.

### Partial success / dropped_data_points on metrics export

#### Symptom

Logs mostram "Partial success response" com `dropped_data_points > 0`, e mensagens tipo "Unsupported metric: 'X' - Reason: UNSUPPORTED_METRIC_TYPE_CUMULATIVE_HISTOGRAM" ou "..._MONOTONIC_CUMULATIVE_SUM". Traces/logs continuam a funcionar; só métricas específicas são descartadas.

#### Possible causes

- Dynatrace exige delta temporality para métricas ingeridas via OTLP; o SDK OTel (a maioria das linguagens, incluindo Python) envia cumulative temporality por omissão.

#### How to check & fix

Confirmar que o processor `cumulativetodelta` está presente no pipeline de métricas, antes do `batch` (já incluído por omissão neste repo desde 2026-07-03). Documentação oficial: https://docs.dynatrace.com/docs/ingest-from/opentelemetry/collector/configuration

Note: after restarting the collector, it's expected to see ONE occurrence of this warning on the first metrics export cycle — the cumulativetodelta processor has no baseline yet to compute a delta from. If the warning does not repeat on subsequent cycles (~30-60s apart), the fix is working correctly.

## Collector healthy, Dynatrace OK, but no new data arrives

### Symptom

The Collector is `Up`, the health check returns 200, and there are no export errors in the logs — but no new traces/metrics appear in Dynatrace.

### Possible causes

- The app is not instrumented, or the OpenTelemetry SDK was not initialized.
- The app is sending to the wrong OTLP host/port (does not match the Collector's 4317 / 4318).
- Protocol/port mismatch — app uses gRPC (4317) vs HTTP (4318), or uses TLS while the receiver expects plaintext.
- App and Collector run on different Docker networks → the Collector service name does not resolve from the app container.
- The app simply is not generating traffic (no requests → no spans).

### How to check & fix

Prove that the Collector receives something by sending a test OTLP request to the HTTP receiver:

```bash
curl -v -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
```

Temporarily increase visibility in the Collector itself to see what comes in — add a `debug` (or `logging`) exporter to the pipeline, or increase `service::telemetry`, then watch the logs.

Check the app's OTLP configuration: endpoint, port, and protocol must match the receiver.

In docker‑compose: confirm that app and Collector share the same network and that the app uses the Collector service name (not `localhost`).

Confirm the app is actually getting traffic — without activity, there is no telemetry to send.

## [LEGACY — Track B aposentado] Dify workflow exporter is healthy, but node spans do not appear

### Symptom

`curl http://localhost:8088/healthz` works, workflow calls still return Dify
responses, but Dynatrace does not show workflow node spans.

### Possible causes

- The client is still calling Dify directly instead of the exporter on port `8088`.
- The workflow is executed with `response_mode=blocking`. Dify only exposes
  node-level events during streaming/resume event flows.
- The exporter cannot reach the Dify API service on `http://api:5001`.
- The exporter cannot reach `otel-collector:4318`.
- The Dify response stream does not include `node_started` / `node_finished`
  events for the path being called.

### How to check & fix

Confirm the exporter can reach Dify and the collector on the shared network:

```bash
docker compose -f legacy/docker-compose.workflow-exporter.yaml exec dify-workflow-otel-exporter python -c "import socket; print(socket.gethostbyname('api')); print(socket.gethostbyname('otel-collector'))"
```

Call the exporter with streaming mode:

```bash
curl --request POST \
  --url http://localhost:8088/v1/workflows/run \
  --header 'Authorization: Bearer <dify-app-api-key>' \
  --header 'Content-Type: application/json' \
  --data '{"inputs":{},"response_mode":"streaming","user":"otel-test"}'
```

Then check exporter and collector logs:

```bash
docker compose -f legacy/docker-compose.workflow-exporter.yaml logs --tail 100 dify-workflow-otel-exporter
cd examples/docker-compose
docker compose logs --tail 100 otel-collector
```

If the same workflow call is sent directly to Dify, bypassing port `8088`,
this exporter cannot observe it.

## Dify: web (Next.js) returns 502 on `/`

### Symptom

Nginx returns `502 Bad Gateway` for `/` (the Dify web UI itself), while `/console/api/*` and other backend routes work fine.

### Possible causes

- The Next.js standalone server (`web` container) binds to `process.env.HOSTNAME`. When the container is attached to multiple Docker networks, `/etc/hosts` resolves the container hostname to the IP of only one of those networks — so the server ends up listening on a single interface instead of all of them.
- Nginx typically reaches `web` over a different network than the one the hostname happened to resolve to, so the connection is refused from nginx's side.

### How to check & fix

```bash
docker logs <nginx-container> | grep -i "connect() failed"
docker exec <web-container> sh -c 'echo $HOSTNAME; netstat -tlnp 2>/dev/null || ss -tlnp'
```

Confirm the `web` process is only listening on one IP instead of `0.0.0.0`.

Fix: force the server to bind on all interfaces by setting `HOSTNAME=0.0.0.0` on the `web` service. This is already applied in [`docker-compose.override.dify-example.yaml`](../docker-compose.override.dify-example.yaml) in this repo — copy it into the Dify `docker/` install directory as `docker-compose.override.yaml`.

## Dify: `/console/api/*` returns 502 after recreating the `api` container

### Symptom

`/console/api/*` starts returning `502 Bad Gateway` right after `api` (or `worker`) is recreated — for example after `docker compose up -d --force-recreate api`, or after any change that replaces the container. Symptoms in the UI include Knowledge/Datasets stuck in an endless loading state.

### Possible causes

- Nginx's `proxy_pass` resolves the upstream hostname to an IP **once**, at nginx startup, and caches it for the life of the worker process — this is default behavior unless a `resolver` directive with a variable in `proxy_pass` is configured.
- When `api` is recreated, Docker assigns it a new internal IP. Nginx keeps sending traffic to the old (now dead) IP → connection refused → 502.
- Nginx itself did not restart, so it never re-resolves the name.

### How to check & fix

Compare the IP nginx is actually using against the container's current IP:

```bash
docker exec <nginx-container> getent hosts api          # current, real IP
docker logs <nginx-container> | grep -i upstream         # IP nginx is failing to reach
```

If they differ, that confirms the stale-DNS-cache theory.

**Immediate fix** — force nginx to re-resolve by reloading it:

```bash
docker exec <nginx-container> nginx -s reload
```

**Permanent fix** (apply on the Dify install, not managed by this repo) — configure nginx to resolve dynamically instead of caching at startup, using Docker's embedded DNS resolver and a variable in `proxy_pass`:

```nginx
resolver 127.0.0.11 valid=10s;
set $api_upstream api:5001;
proxy_pass http://$api_upstream;
```

This repo does not manage Dify's `nginx.conf` — treat this as a recommendation to apply directly in the Dify installation.

## Dify: `api`/`worker` cannot resolve `otel-collector` (`NameResolutionError`)

### Symptom

`api` or `worker` logs show `NameResolutionError` or similar DNS failures when trying to reach `otel-collector`, even though the collector is `Up` and was reachable before.

### Possible causes

- The `dify-otel-net` network was attached to the container manually with `docker network connect` instead of being declared in the compose/override file.
- Manual `docker network connect` attachments do **not** survive `docker compose up -d --force-recreate` (or any recreate) — Compose rebuilds the container from the declared `networks:` list only, dropping any connection that was added out-of-band.

### How to check & fix

```bash
docker inspect <api-container> --format '{{json .NetworkSettings.Networks}}'
```

Confirm `dify-otel-net` is present. If it disappeared after a recreate, it was attached manually and needs to be declared instead.

Fix: make sure `dify-otel-net` is listed under `networks:` for both `api` and `worker` in `docker-compose.override.dify-example.yaml` — already included in this repo — so the network survives any recreate.

## Dify: `CSRF token is missing` (401) hitting `/console/api/*` directly

### Symptom

Opening a `/console/api/*` URL directly in the browser (e.g. to sanity-check an endpoint) returns `401` with a body like `CSRF token is missing`.

### Possible causes

This is not a bug. Console API endpoints require a CSRF token that the Dify web app attaches automatically on its own AJAX requests. A bare browser navigation to the URL never carries that token, so it is rejected by design.

### How to check & fix

Do not use this as a health signal. Instead:

- Validate through the authenticated app itself (open the feature in the Dify UI and check the network tab).
- Or hit an endpoint that does not require a session, such as `/console/api/version`, to confirm the API is reachable at all.

## Quick reference

| Goal                                 | Command                                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Container status                     | `docker compose ps`                                                                                          |
| Follow Collector logs                | `docker compose logs -f otel-collector`                                                                      |
| Health check                         | `curl -v http://localhost:13133`                                                                             |
| Print env vars inside the container  | `docker compose exec otel-collector printenv`                                                                |
| Validate Collector config            | `docker compose run --rm otel-collector validate --config /etc/otelcol-contrib/config.yaml`                          |
| Check host ports in use              | `lsof -i :4317 ; lsof -i :4318 ; lsof -i :13133`                                                             |
| Test OTLP send (HTTP)                | `curl -X POST http://localhost:4318/v1/traces -H "Content-Type: application/json" -d '{"resourceSpans":[]}'` |
| Clean restart                        | `docker compose down && docker compose up -d`                                                                 |
| Dify: reload nginx (stale upstream)  | `docker exec <nginx-container> nginx -s reload`                                                               |
| Dify: check container's real IP      | `docker exec <nginx-container> getent hosts api`                                                              |
| Dify: check declared networks        | `docker inspect <api-container> --format '{{json .NetworkSettings.Networks}}'`                                |
