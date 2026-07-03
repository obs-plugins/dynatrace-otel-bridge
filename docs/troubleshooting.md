Troubleshooting
This guide helps you isolate issues in the bridge telemetry chain:

text
app  ──OTLP──▶  Collector  ──OTLP/HTTP──▶  Dynatrace
             (4317 gRPC /              (otlphttp exporter:
              4318 HTTP)                DT_OTLP_ENDPOINT + DT_API_TOKEN)
Always diagnose from the inside out, in this order:

The Collector starts and stays up.

The Collector is healthy (health check responds).

The Collector talks to Dynatrace (exports without HTTP errors).

The app sends telemetry to the Collector.

Skipping steps usually means you end up debugging in the wrong place. Follow the order of the sections below.

Before you start
Quick checklist before any troubleshooting:

.env present and filled in — copied from .env.example with all required variables set:

DT_OTLP_ENDPOINT — OTLP/HTTP endpoint of your Dynatrace tenant.

DT_API_TOKEN — token with the required OTLP ingest scope.

Host ports are free — 4317 (OTLP gRPC), 4318 (OTLP HTTP), and 13133 (health check).

Basic commands (run from the compose folder, for example examples/docker-compose/):

bash
docker compose up -d           # start in background
docker compose ps              # check container status
docker compose logs -f otel-collector   # follow Collector logs
If .env is not filled in, the Collector may not even start (see next section).

Collector does not start (crash / restart loop)
Symptom

docker compose up fails immediately, or the container keeps going to Restarting / Exited instead of Up.

docker compose ps shows a state different from running / Up.

Possible causes

Syntax or indentation error in otelcol-config.yaml (invalid YAML).

Mis‑referenced pipeline — a receiver / processor / exporter is listed in service.pipelines but not defined above.

Missing .env → required variable ends up empty and the config cannot expand it.

Host port already in use (4317, 4318 or 13133) → bind failure.

Collector image/tag does not exist or was not pulled.

How to check & fix

bash
docker compose ps                               # status and restart count
docker compose logs otel-collector --tail=50    # first error line usually shows the cause
The first error line from the Collector is usually explicit:
error decoding 'exporters', cannot bind to address, undefined receiver, and so on.

Validate the config without starting the full service:

bash
docker compose run --rm otel-collector validate --config /etc/otelcol/config.yaml
(the subcommand may be otelcol validate, depending on the distro/image).

Check if any port is already in use on the host:

bash
lsof -i :4317 ; lsof -i :4318 ; lsof -i :13133
Confirm that .env exists and is filled in (see Before you start).

Health check fails (curl http://localhost:13133)
Symptom

curl http://localhost:13133 returns connection refused, times out, or responds with a status other than 200.

Possible causes

health_check extension is not enabled in otelcol-config.yaml (missing from service.extensions).

Container is still starting up or has already crashed (ties back to the previous section).

Port 13133 is not mapped in docker-compose.yaml, or is mapped to a different host port.

You are testing from a different machine/network — the mapping is only for localhost.

How to check & fix

bash
docker compose ps                 # is the container actually Up?
curl -v http://localhost:13133    # distinguish "refused" from an HTTP response
If the container is not Up, go back to Collector does not start.

Connection refused = nothing is listening on that port; non‑200 HTTP response = service is up but health is reporting a problem.

Confirm that health_check is listed under service::extensions in the config and that 13133:13133 is present in the compose file.

Test from inside the container (isolates app vs host port mapping):

bash
docker compose exec otel-collector wget -qO- localhost:13133
Collector starts but Dynatrace receives no data
Symptom

The Collector is Up and the health check returns 200, but no data shows up in Dynatrace.
Collector logs show otlphttp exporter errors with an HTTP status code.

Cross‑check — find the status code returned by the endpoint:

bash
docker compose logs otel-collector | grep -Ei "otlphttp|export|status|permanent"
401 / 403 — authentication
Possible causes

DT_API_TOKEN invalid or expired.

Token is missing the required OTLP ingest scope.

Malformed authorization header.

How to check & fix

bash
docker compose exec otel-collector printenv DT_API_TOKEN   # confirm it is set
Confirm that the token exists inside the container (not only in the host .env).

Verify that the token has the required OTLP ingest scope in Dynatrace.

Call the endpoint directly, sending the token header, to see which status code it returns:

bash
curl -v -X POST "$DT_OTLP_ENDPOINT" \
  -H "Authorization: Api-Token dt0c01.XXXX" \
  -H "Content-Type: application/x-protobuf"
404 — wrong endpoint
Possible causes

DT_OTLP_ENDPOINT has an incorrect host or path (missing the proper OTLP path, extra or missing /, or wrong tenant).

How to check & fix

bash
docker compose exec otel-collector printenv DT_OTLP_ENDPOINT
Compare the value with the expected Dynatrace OTLP endpoint format.

Run curl -v "$DT_OTLP_ENDPOINT" to see if the path exists (404 vs some other response).

5xx / timeouts / connection issues
Possible causes

Temporary Dynatrace backend unavailability.

Network, proxy, or firewall issues blocking HTTPS egress.

DNS failures inside the container.

How to check & fix

bash
docker compose exec otel-collector wget -qO- https://<endpoint-host>   # DNS + connectivity
Ensure DNS resolution and connectivity from inside the container to the endpoint host.

Confirm that HTTPS egress is not blocked by a proxy or firewall.

Note: the otlphttp exporter retries with backoff — transient 5xx errors may recover on their own; 4xx marked as permanent will not recover and data is dropped.

Collector healthy, Dynatrace OK, but no new data arrives
Symptom

The Collector is Up, the health check returns 200, and there are no export errors in the logs — but no new traces/metrics appear in Dynatrace.

Possible causes

The app is not instrumented, or the OpenTelemetry SDK was not initialized.

The app is sending to the wrong OTLP host/port (does not match the Collector’s 4317 / 4318).

Protocol/port mismatch — app uses gRPC (4317) vs HTTP (4318), or uses TLS while the receiver expects plaintext.

App and Collector run on different Docker networks → the Collector service name does not resolve from the app container.

The app simply is not generating traffic (no requests → no spans).

How to check & fix

Prove that the Collector receives something by sending a test OTLP request to the HTTP receiver:

bash
curl -v -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
Temporarily increase visibility in the Collector itself to see what comes in — add a debug (or logging) exporter to the pipeline, or increase service::telemetry, then watch the logs.

Check the app’s OTLP configuration: endpoint, port, and protocol must match the receiver.

In docker‑compose: confirm that app and Collector share the same network and that the app uses the Collector service name (not localhost).

Confirm the app is actually getting traffic — without activity, there is no telemetry to send.

| Goal                                | Command                                                                                                    |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Container status                    | docker compose ps                                                                                          |
| Follow Collector logs               | docker compose logs -f otel-collector                                                                      |
| Health check                        | curl -v http://localhost:13133                                                                             |
| Print env vars inside the container | docker compose exec otel-collector printenv                                                                |
| Validate Collector config           | docker compose run --rm otel-collector validate --config /etc/otelcol/config.yaml                          |
| Check host ports in use             | lsof -i :4317 ; lsof -i :4318 ; lsof -i :13133                                                             |
| Test OTLP send (HTTP)               | curl -X POST http://localhost:4318/v1/traces -H "Content-Type: application/json" -d '{"resourceSpans":[]}' |
| Clean restart                       | docker compose down && docker compose up -d                                                                |
