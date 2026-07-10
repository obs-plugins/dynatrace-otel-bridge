# Legacy — Track B (Dify Workflow OTel Exporter)

This directory contains **Track B**, retired in v1.

## What it was
A reverse-proxy (FastAPI + httpx) that sat in front of Dify's Workflow API
(port 8088), intercepted `/v1/workflows/run`, parsed the SSE stream, and
emitted OTel spans with GenAI attributes, plus a token metric
(`gen_ai.client.token.usage`) via a MeterProvider.

## Why it was retired
Dify now emits mature native OTel instrumentation at the GraphEngine level
(`ObservabilityLayer`), covering all invocation paths (Studio, WebApp, API,
Debugger) — a superset of what the proxy covered (synchronous HTTP on 8088 only).
The OTTL conformance processors in the Collector (Fatias 1–8) normalize the
native dialect to the official conventions, and the Dynatrace AI Observability
app populates tokens/cost from span attributes, without needing the dedicated metric.

Parity test (exporter stopped): LLM node spans, models, tokens, and provider
kept arriving via `langgenius/dify`; `dify-workflow-otel-exporter` stopped
emitting. Track B confirmed redundant.

## If you need it in the future
The token MeterProvider logic (`main.py`) can be reused if a metric requirement
arises that Track A doesn't satisfy. The `sumconnector` is NOT in the
dynatrace/dynatrace-otel-collector distribution, so reintroducing token metrics
via the Collector would require a custom build (OCB).
